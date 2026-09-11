"""Read one SES sending event off the SNS payload.

No ORM and no Django settings in here: pure dict-in, dataclass-out, so it stays in the fast unit
suite that runs without a database.

SES speaks two dialects for the same thing. A configuration set's event destination writes
`eventType`; the older per-identity SNS notifications write `notificationType`. Both are read.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

DELIVERY = 'Delivery'
OPEN = 'Open'
BOUNCE = 'Bounce'
COMPLAINT = 'Complaint'

# Everything else SES can publish (Send, Reject, Click, DeliveryDelay, Subscription,
# RenderingFailure) says nothing a message row should carry.
HANDLED_EVENT_TYPES = (DELIVERY, OPEN, BOUNCE, COMPLAINT)

# The key the event's own body hangs off: {"eventType": "Open", "open": {...}}.
_EVENT_KEY = {DELIVERY: 'delivery', OPEN: 'open', BOUNCE: 'bounce', COMPLAINT: 'complaint'}


@dataclass(frozen=True)
class SesEvent:
    event_type: str  # one of HANDLED_EVENT_TYPES
    ses_message_id: str  # mail.messageId, raw — not yet the RFC 5322 form we store
    at: datetime | None  # when it happened, timezone-aware; None if SES sent nothing usable
    reason: str  # bounces only, for error_message; '' otherwise


def parse_ses_timestamp(value: str) -> datetime | None:
    """SES sends ISO 8601 with a Z: '2016-10-19T23:21:04.133Z'.

    The result has to be aware: USE_TZ is on, and Django warns then guesses on a naive one.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def build_bounce_reason(bounce_obj: dict) -> str:
    """What to show the admin under the red triangle.

    The type and subtype say whether it is worth retrying (Permanent/General vs
    Transient/MailboxFull); the diagnosticCode is the remote server's own words, which is what
    actually names the problem.
    """
    header = '/'.join(one for one in (bounce_obj.get('bounceType'),
                                      bounce_obj.get('bounceSubType')) if one)
    codes = [recipient.get('diagnosticCode', '')
             for recipient in bounce_obj.get('bouncedRecipients') or []]
    detail = ' '.join(code for code in codes if code)
    if header and detail:
        return f'{header} — {detail}'
    return header or detail


def parse_ses_event(event_message: dict) -> SesEvent | None:
    """One SES event, or None for anything we have nothing to do with."""
    event_type = event_message.get('eventType') or event_message.get('notificationType')
    if event_type not in HANDLED_EVENT_TYPES:
        return None

    ses_message_id = (event_message.get('mail') or {}).get('messageId') or ''
    if not ses_message_id:
        # Nothing to correlate on: the event names no mail of ours.
        return None

    event_obj = event_message.get(_EVENT_KEY[event_type]) or {}
    return SesEvent(
        event_type=event_type,
        ses_message_id=ses_message_id,
        # The event's own timestamp is when it happened; mail.timestamp is only when we sent.
        at=parse_ses_timestamp(event_obj.get('timestamp', '')),
        reason=build_bounce_reason(event_obj) if event_type == BOUNCE else '',
    )
