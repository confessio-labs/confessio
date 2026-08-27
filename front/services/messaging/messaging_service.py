"""Send and receive the admin messaging's emails.

Four flows feed the same Conversation, which is the source of truth:

  - the contact form, recorded on the spot and mirrored to the contact mailbox;
  - a send from /messaging, mailed to the correspondent through SES;
  - a mail received on the contact address, handed over by Mailgun's inbound route;
  - a mail sent from the contact mailbox, reported by Mailgun's event webhook.

Everything we mail to the contact address goes out from no-reply@, which is precisely what the
inbound webhook filters on so our own mirrors never come back in as new messages.
"""
import os

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.mail import BadHeaderError, EmailMultiAlternatives
from django.urls import reverse
from django.utils import timezone
from email.utils import formataddr

from core.utils.discord_utils import DiscordChanel, send_discord_alert
from front.models import Conversation, Message
from front.utils.messaging_utils import (HistoryEntry, build_outbound_bodies,
                                         build_reply_subject, build_ses_message_id,
                                         build_thread_headers, extract_conversation_uuid,
                                         first_external_address, is_automated_sender,
                                         is_same_email, parse_message_ids, parse_sender)

# Discord rejects anything past 2000 characters, and a long mail adds nothing to an alert whose
# job is to hand over the link.
MAX_DISCORD_BODY = 1200


def get_conversation_url(request, conversation: Conversation) -> str:
    return request.build_absolute_uri(reverse('messaging_view', args=[conversation.uuid]))


def get_home_url(request) -> str:
    return request.build_absolute_uri(reverse('home'))


def _build_mail(subject: str, content: str, entries: list[HistoryEntry], request,
                conversation: Conversation, always_footer: bool = False,
                **kwargs) -> EmailMultiAlternatives:
    """One mail, two parts. The text part is the one that matters on the way back: Mailgun strips
    it at the footer's `--` and we read the thread key out of it."""
    text_body, html_body = build_outbound_bodies(content, entries,
                                                 get_conversation_url(request, conversation),
                                                 get_home_url(request),
                                                 always_footer=always_footer)
    mail = EmailMultiAlternatives(subject=subject, body=text_body, **kwargs)
    mail.attach_alternative(html_body, 'text/html')
    return mail


def send_message(request, conversation: Conversation, body: str, author) -> Message:
    """Record an outgoing message and mail it to the correspondent.

    Sending is synchronous: a failure is stored on the row rather than raised, so the admin sees
    it in the thread and can retry by sending again.
    """
    # Read the thread before adding to it: these are the mails the new one answers and quotes.
    previous = list(conversation.messages.select_related('author', 'conversation').all())
    # The very first message of a thread carries the bare subject; anything after it is a reply.
    is_first = not previous

    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        body=body,
        author=author,
        status=Message.Status.SENT,
    )
    email = _build_mail(
        # From is CONTACT_EMAIL, not DEFAULT_FROM_EMAIL: it is the address Mailgun routes back
        # to our webhook, so the answer reaches the thread by simply hitting reply. A no-reply@
        # From would tell the correspondent not to do the one thing this feature needs. No
        # Reply-To then: it would only repeat the From.
        subject=build_reply_subject(conversation.subject, is_first),
        content=body,
        entries=_history_entries(previous),
        request=request,
        conversation=conversation,
        from_email=formataddr(('Confessio', os.environ.get('CONTACT_EMAIL'))),
        to=[conversation.email],
        headers=build_thread_headers([one.message_id for one in previous]),
    )
    _send_and_record(message, email)

    _touch(conversation)
    return message


def record_contact_form(request, name: str, email: str, subject: str, body: str) -> Message:
    """Open a conversation on a contact form submission, and mirror it to the contact mailbox.

    The submission is kept before anything is mailed: it is captured even if SES is down, in which
    case the failure shows on the message in /messaging.
    """
    conversation = Conversation.objects.create(email=_fit(Conversation, 'email', email),
                                               name=_fit(Conversation, 'name', name),
                                               subject=_fit(Conversation, 'subject', subject))
    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body=body,
        from_email=_fit(Message, 'from_email', formataddr((name, email))),
        status=Message.Status.RECEIVED,
    )
    _notify_discord(request, message)

    mail = _build_mail(
        # SES only accepts a verified identity as From, so the visitor goes in Reply-To: hitting
        # reply in the contact mailbox answers them directly.
        subject=conversation.subject,
        content=body,
        entries=[],
        request=request,
        conversation=conversation,
        always_footer=True,
        from_email=formataddr((f'{name} (via Confessio)', settings.DEFAULT_FROM_EMAIL)),
        to=[os.environ.get('CONTACT_EMAIL')],
        reply_to=[formataddr((name, email))],
    )
    # The mirror is what the contact mailbox threads on, so its id is the one worth keeping.
    _send_and_record(message, mail)

    _touch(conversation)
    return message


def ingest_received_email(request, from_header: str, reply_to: str, subject: str,
                          body_plain: str, stripped_text: str, body_html: str = '',
                          message_id: str = '', in_reply_to: str = '',
                          references: str = '') -> Message | None:
    """Turn one mail received on the contact address into a message.

    Returns None for mail nobody could answer (bounces, auto-responders) and for a delivery we
    already recorded. Anything else is kept, even if we cannot make sense of the sender — a
    visible junk conversation beats a submission dropped in silence.
    """
    name, email = parse_sender(reply_to, from_header)
    if not email or is_automated_sender(email):
        return None
    if _is_duplicate(message_id):
        return None

    conversation = find_conversation(body_plain, stripped_text, body_html,
                                     in_reply_to, references)
    is_new = conversation is None
    if is_new:
        conversation = Conversation.objects.create(email=_fit(Conversation, 'email', email),
                                                   name=_fit(Conversation, 'name', name),
                                                   subject=_fit(Conversation, 'subject', subject))

    # Mailgun's stripped-text already removed the quoted thread below the reply.
    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body=stripped_text or body_plain,
        from_email=_fit(Message, 'from_email', from_header),
        status=Message.Status.RECEIVED,
        message_id=_fit(Message, 'message_id', message_id),
    )
    _touch(conversation)
    _notify_discord(request, message)

    if is_new:
        _mirror_to_contact_mailbox(request, conversation, message)
    return message


def ingest_sent_email(from_header: str, to_header: str, subject: str,
                      body_plain: str, stripped_text: str, body_html: str = '',
                      message_id: str = '', in_reply_to: str = '',
                      references: str = '') -> Message | None:
    """Record a reply the admin wrote in the contact mailbox, outside /messaging.

    Mailgun keeps no copy of what our domain sends, so the only way to see such a reply is to be
    sent one: the mail client puts ARCHIVE_EMAIL in Bcc, and that copy comes back through the
    inbound route like any other mail.
    """
    if not is_same_email(from_header, os.environ.get('CONTACT_EMAIL', '')):
        # A correspondent's reply-all reaches the archive address too. That one is inbound mail,
        # and the contact address already received its own copy of it.
        print(f"Ignoring archived mail not sent from the contact address: {from_header}")
        return None

    if _is_duplicate(message_id):
        return None

    conversation = find_conversation(body_plain, stripped_text, body_html,
                                     in_reply_to, references)
    if conversation is None:
        ours = (os.environ.get('CONTACT_EMAIL', ''), os.environ.get('ARCHIVE_EMAIL', ''),
                settings.DEFAULT_FROM_EMAIL)
        name, email = first_external_address(to_header, ours)
        if not email:
            # A conversation we could never mail back to is worse than no conversation.
            return None
        conversation = Conversation.objects.create(email=_fit(Conversation, 'email', email),
                                                   name=_fit(Conversation, 'name', name),
                                                   subject=_fit(Conversation, 'subject', subject))

    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        # Nobody typed this in /messaging, so there is no author to credit.
        body=stripped_text or body_plain,
        from_email=_fit(Message, 'from_email', from_header),
        status=Message.Status.SENT,
        message_id=_fit(Message, 'message_id', message_id),
    )
    _touch(conversation)
    return message


def find_conversation(body_plain: str, stripped_text: str, body_html: str = '',
                      in_reply_to: str = '', references: str = '') -> Conversation | None:
    """Attach an incoming mail to the thread it belongs to, or None to open a new one.

    Our own link comes first: it names the conversation outright. The HTML part is searched too —
    the footer shows the link as a word, so the url only survives in the href. The Message-IDs are
    the fallback for a client that answered without quoting anything.
    """
    conversation_uuid = extract_conversation_uuid(body_plain, stripped_text, body_html)
    if conversation_uuid:
        conversation = Conversation.objects.filter(uuid=conversation_uuid).first()
        if conversation:
            return conversation

    message_ids = parse_message_ids(in_reply_to, references)
    if not message_ids:
        return None
    by_message_id = {one.message_id: one for one
                     in Message.objects.filter(message_id__in=message_ids)
                     .select_related('conversation')}
    for message_id in message_ids:
        if message_id in by_message_id:
            return by_message_id[message_id].conversation
    return None


def _mirror_to_contact_mailbox(request, conversation: Conversation, message: Message) -> None:
    """Hand the conversation link to the contact mailbox, once, when a thread opens there.

    The correspondent's mail already reached that mailbox — what it lacks is our link, without
    which a reply written from the mail client could only be threaded back by Message-ID. Sent
    from no-reply@ so the inbound webhook ignores it on the way back in, and threaded onto the
    mail it announces so both sit in the same conversation.
    """
    name = conversation.name or conversation.email
    mail = _build_mail(
        subject=build_reply_subject(conversation.subject, is_first=False),
        content='',
        entries=_history_entries([message]),
        request=request,
        conversation=conversation,
        always_footer=True,
        from_email=formataddr((f'{name} (via Confessio)', settings.DEFAULT_FROM_EMAIL)),
        to=[os.environ.get('CONTACT_EMAIL')],
        reply_to=[formataddr((conversation.name, conversation.email))],
        headers=build_thread_headers([message.message_id]),
    )
    try:
        mail.send()
    except (BadHeaderError, BotoCoreError, ClientError) as e:
        # The message is already recorded and Discord already rang: the mirror is a convenience.
        print(e)


def _send_and_record(message: Message, email: EmailMultiAlternatives) -> None:
    """Mail it out, then keep the id it went out under so the next mail can quote it."""
    try:
        email.send()
    except (BadHeaderError, BotoCoreError, ClientError) as e:
        print(e)
        message.status = Message.Status.FAILED
        message.error_message = str(e)
        message.save(update_fields=['status', 'error_message', 'updated_at'])
        return

    # django-ses writes the id SES assigned back into extra_headers once the send succeeded.
    message.message_id = build_ses_message_id(
        email.extra_headers.get('message_id', ''),
        getattr(settings, 'AWS_SES_REGION_NAME', ''))
    if message.message_id:
        message.save(update_fields=['message_id', 'updated_at'])


def _fit(model, field_name: str, value: str) -> str:
    """Clip a header to the column it lands in.

    Nothing bounds the length of a Subject or a display name, and create() hands the value straight
    to Postgres, which rejects the whole row rather than clipping it — losing the mail over a long
    subject. A shortened subject beats a conversation that never existed.
    """
    return (value or '')[:model._meta.get_field(field_name).max_length]


def _is_duplicate(message_id: str) -> bool:
    """Mailgun replays a webhook it could not deliver: the same mail must not land twice."""
    return bool(message_id) and Message.objects.filter(message_id=message_id).exists()


def _history_entries(messages: list[Message]) -> list[HistoryEntry]:
    """Turn stored messages into what the quoted history needs, oldest first."""
    return [HistoryEntry(
        label=_label(message),
        sent_at=timezone.localtime(message.created_at).strftime('%d/%m/%Y à %H:%M'),
        body=message.body,
        is_outbound=message.direction == Message.Direction.OUTBOUND,
    ) for message in messages]


def _label(message: Message) -> str:
    if message.direction == Message.Direction.OUTBOUND:
        return message.author.username if message.author else 'Confessio'
    name, email = parse_sender('', message.from_email)
    return name or email or message.conversation.name or message.conversation.email


def _notify_discord(request, message: Message) -> None:
    conversation = message.conversation
    body = message.body[:MAX_DISCORD_BODY]
    send_discord_alert(
        message=f"**{conversation.subject}**\n"
                f"De : {message.from_email or conversation.email}\n\n"
                f"{body}\n\n"
                f"{get_conversation_url(request, conversation)}",
        channel=DiscordChanel.CONTACT_FORM)


def _touch(conversation: Conversation) -> None:
    """Bump updated_at so the thread rises to the top of the sidebar."""
    conversation.save(update_fields=['updated_at'])
