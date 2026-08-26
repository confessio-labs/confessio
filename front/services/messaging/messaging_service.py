"""Send and receive the admin messaging's emails.

Outgoing mail goes out through SES (like the contact form), incoming mail comes back through the
Mailgun inbound webhook. The two are tied together by the conversation link in the body footer.
"""
import os

from botocore.exceptions import ClientError
from django.conf import settings
from django.core.mail import BadHeaderError, EmailMessage
from django.urls import reverse
from email.utils import formataddr

from front.models import Conversation, Message
from front.utils.messaging_utils import (append_conversation_footer, build_reply_subject,
                                         build_ses_message_id, build_thread_headers,
                                         extract_conversation_uuid, is_automated_sender,
                                         parse_sender)


def get_conversation_url(request, conversation: Conversation) -> str:
    return request.build_absolute_uri(reverse('messaging_view', args=[conversation.uuid]))


def send_message(request, conversation: Conversation, body: str, author) -> Message:
    """Record an outgoing message and mail it to the correspondent.

    Sending is synchronous: a failure is stored on the row rather than raised, so the admin sees
    it in the thread and can retry by sending again.
    """
    # Read the thread before adding to it: these are the mails the new one answers.
    previous_message_ids = list(conversation.messages.values_list('message_id', flat=True))
    # The very first message of a thread carries the bare subject; anything after it is a reply.
    is_first = not previous_message_ids

    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        body=body,
        author=author,
        status=Message.Status.SENT,
    )
    email = EmailMessage(
        # From is CONTACT_EMAIL, not DEFAULT_FROM_EMAIL: it is the address Mailgun routes back
        # to our webhook, so the answer reaches the thread by simply hitting reply. A no-reply@
        # From would tell the correspondent not to do the one thing this feature needs. No
        # Reply-To then: it would only repeat the From.
        subject=build_reply_subject(conversation.subject, is_first),
        body=append_conversation_footer(body, get_conversation_url(request, conversation)),
        from_email=formataddr(('Confessio', os.environ.get('CONTACT_EMAIL'))),
        to=[conversation.email],
        headers=build_thread_headers(previous_message_ids),
    )
    try:
        email.send()
    except (BadHeaderError, ClientError) as e:
        print(e)
        message.status = Message.Status.FAILED
        message.error_message = str(e)
        message.save(update_fields=['status', 'error_message', 'updated_at'])
    else:
        # django-ses writes the id SES assigned back into extra_headers once the send succeeded.
        message.message_id = build_ses_message_id(
            email.extra_headers.get('message_id', ''),
            getattr(settings, 'AWS_SES_REGION_NAME', ''))
        if message.message_id:
            message.save(update_fields=['message_id', 'updated_at'])

    _touch(conversation)
    return message


def ingest_inbound_email(from_header: str, reply_to: str, subject: str,
                         body_plain: str, stripped_text: str,
                         message_id: str = '') -> Message | None:
    """Turn one inbound Mailgun mail into a message, opening a conversation if it is a new thread.

    Returns None only for mail nobody could answer: bounces and auto-responders. Anything else is
    kept, even if we cannot make sense of the sender — a visible junk conversation beats a
    submission dropped in silence.

    A contact-form mail goes through here like any other incoming message (it is addressed to
    CONTACT_EMAIL, which Mailgun routes back to us), so the contact view has nothing to do. Its
    From is our own no-reply@ — SES only accepts a verified identity — and the visitor is in
    Reply-To, which parse_sender prefers.
    """
    name, email = parse_sender(reply_to, from_header)
    if not email or is_automated_sender(email):
        return None

    conversation = None
    conversation_uuid = extract_conversation_uuid(body_plain, stripped_text)
    if conversation_uuid:
        conversation = Conversation.objects.filter(uuid=conversation_uuid).first()
    if conversation is None:
        conversation = Conversation.objects.create(email=email, name=name, subject=subject)

    # Mailgun's stripped-text already removed the quoted thread below the reply.
    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body=stripped_text or body_plain,
        from_email=from_header,
        status=Message.Status.RECEIVED,
        message_id=message_id,
    )
    _touch(conversation)
    return message


def _touch(conversation: Conversation) -> None:
    """Bump updated_at so the thread rises to the top of the sidebar."""
    conversation.save(update_fields=['updated_at'])
