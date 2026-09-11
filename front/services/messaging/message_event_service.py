"""Apply what SES tells us about a mail to the message row it went out under.

The correlation key already exists: SES overwrites the Message-ID we hand it with one derived
from the id it returns to the API, `_send_and_record` stores that, and the event carries the same
raw id back in mail.messageId.
"""
from django.conf import settings
from django.utils import timezone

from front.models import Message
from front.utils.messaging_utils import build_ses_message_id
from front.utils.ses_utils import BOUNCE, COMPLAINT, DELIVERY, OPEN, SesEvent, parse_ses_event


def record_mail_event(event_message: dict) -> None:
    """Store one SES sending event, or do nothing at all — the two normal outcomes."""
    event = parse_ses_event(event_message)
    if event is None:
        return

    message_id = build_ses_message_id(event.ses_message_id,
                                      getattr(settings, 'AWS_SES_REGION_NAME', ''))
    if not message_id:
        return

    # Outbound only. A contact-form submission is an inbound row, yet the mail we mirror to our
    # own mailbox goes out under its id (`record_contact_form` -> `_send_and_record`): an open on
    # that one would say nothing but "we read our own mailbox".
    # first(), not get(): message_id carries no unique constraint, and MultipleObjectsReturned
    # inside a webhook is exactly the failure we do not want.
    message = Message.objects.filter(message_id=message_id,
                                     direction=Message.Direction.OUTBOUND).first()
    if message is None:
        # A mail we never recorded: the mirror to the contact mailbox, or a send from a dev
        # machine pointed at the same configuration set.
        return

    _apply(message, event)


def _apply(message: Message, event: SesEvent) -> None:
    """The first event of its kind wins, and that is the whole idempotency story.

    SNS delivers at least once and in no particular order, so a replayed event must change
    nothing and a Delivery landing after its Open must not look like news. Each branch writes
    only its own field, so there is nothing for a late event to undo.
    """
    at = event.at or timezone.now()
    update_fields = []

    if event.event_type == DELIVERY and message.delivered_at is None:
        message.delivered_at = at
        update_fields.append('delivered_at')
    elif event.event_type == OPEN and message.opened_at is None:
        # Only the first open: the pixel reloads every time the mail is displayed.
        message.opened_at = at
        update_fields.append('opened_at')
    elif event.event_type == COMPLAINT and message.complained_at is None:
        message.complained_at = at
        update_fields.append('complained_at')
    elif event.event_type == BOUNCE:
        # Terminal, and the red triangle already renders it. Writing it twice changes nothing.
        message.status = Message.Status.FAILED
        message.error_message = event.reason
        update_fields += ['status', 'error_message']

    if not update_fields:
        return

    # auto_now only fires for fields named in update_fields.
    message.save(update_fields=update_fields + ['updated_at'])
    # Deliberately no _touch(conversation): the sidebar sorts on updated_at, and an image loaded
    # in a two-month-old mail must not shove that thread back to the top.
