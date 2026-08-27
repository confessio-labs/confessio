"""Pure helpers for the admin messaging: no ORM, no service imports, so they stay in the fast
unit-test suite.

Threading is doubly encoded. The conversation link we append to every outgoing body is the first
key: Mailgun drops everything below a `--` signature delimiter from `stripped-text`, so the footer
stays invisible in what we display, while `body-plain` keeps it — which is exactly where we read
the uuid back from when the correspondent replies with our message quoted. The Message-IDs we
store are the second: `In-Reply-To`/`References` name them on the way back in, even when the
correspondent's client dropped the quoted body.
"""
import re
from dataclasses import dataclass
from email.utils import parseaddr

FOOTER_LABEL = 'Identifiant de la conversation'

_UUID = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
# Match the link, not a bare uuid: an unrelated uuid quoted in the mail must not hijack the thread.
CONVERSATION_LINK_RE = re.compile(rf'/messaging/({_UUID})')

# Require the angle brackets and the @: a Message-ID is only ever quoted in that form, and a
# looser pattern would pick words out of a mangled header.
MESSAGE_ID_RE = re.compile(r'<[^<>@\s]+@[^<>\s]+>')

# Senders we never open a conversation for: bounces and auto-responders have nobody to reply to.
AUTOMATED_LOCAL_PARTS = ('mailer-daemon', 'postmaster')


@dataclass(frozen=True)
class HistoryEntry:
    """One past message of a conversation, ready to be quoted in the next mail."""
    label: str  # who wrote it, as it should read in the attribution line
    sent_at: str  # already formatted for display
    body: str
    is_outbound: bool


def conversation_footer(conversation_url: str) -> str:
    return f'--\n{FOOTER_LABEL} : {conversation_url}'


def append_conversation_footer(body: str, conversation_url: str) -> str:
    return f'{body}\n\n{conversation_footer(conversation_url)}'


def extract_conversation_uuid(*texts: str) -> str | None:
    """Find the conversation uuid in the first text that carries our footer link."""
    for text in texts:
        if not text:
            continue
        match = CONVERSATION_LINK_RE.search(text)
        if match:
            return match.group(1)
    return None


def parse_message_ids(*headers: str) -> list[str]:
    """The Message-IDs a mail answers, closest ancestor first, deduplicated.

    `In-Reply-To` names the direct parent; `References` lists the whole chain oldest first, so we
    walk each header backwards — the nearest ancestor is the likeliest to be one of ours.
    """
    message_ids = []
    for header in headers:
        for message_id in reversed(MESSAGE_ID_RE.findall(header or '')):
            if message_id not in message_ids:
                message_ids.append(message_id)
    return message_ids


def parse_sender(reply_to: str, from_header: str) -> tuple[str, str]:
    """Who are we talking to? Reply-To wins over From, as standard mail semantics require.

    This is what recovers the visitor's real address on a mail we mirrored to the contact mailbox:
    SES only accepts a verified identity as From, so we send those from no-reply@ with the
    correspondent in Reply-To.
    """
    for header in (reply_to, from_header):
        name, email = parseaddr(header or '')
        # parseaddr never fails: it hands back the raw string as the address when it cannot parse
        # one ('garbage' -> ('', 'garbage')). Require an @ so a malformed header falls through
        # instead of becoming a conversation we could never mail back to.
        if '@' in email:
            return name, email
    return '', ''


def is_same_email(one: str, other: str) -> bool:
    """Do two address headers name the same mailbox? Display names and case are ignored."""
    one_email = parseaddr(one or '')[1].strip().lower()
    other_email = parseaddr(other or '')[1].strip().lower()
    # parseaddr hands back the raw string when it cannot parse an address, so require an @ before
    # believing it: two identically malformed headers name no mailbox, let alone the same one.
    return '@' in one_email and one_email == other_email


def is_automated_sender(email: str) -> bool:
    local_part = email.split('@')[0].lower()
    return local_part in AUTOMATED_LOCAL_PARTS


def build_reply_subject(subject: str, is_first: bool) -> str:
    if is_first or subject.lower().startswith('re:'):
        return subject
    return f'Re: {subject}'


def build_ses_message_id(ses_message_id: str, region: str) -> str:
    """Rebuild the Message-ID header SES actually delivered.

    SES overwrites whatever Message-ID we hand it and sends its own, derived from the id it returns
    to the API: <{MessageId}@{region}.amazonses.com>. That is what the recipient's client threads
    on, so that is the one worth storing.
    """
    if not ses_message_id or not region:
        return ''
    return f'<{ses_message_id}@{region}.amazonses.com>'


def build_thread_headers(previous_message_ids: list[str]) -> dict[str, str]:
    """Point an outgoing mail at the ones before it in the same conversation.

    Gmail (and most clients) group on References/In-Reply-To, never on the subject alone: without
    these headers every mail we send opens its own thread, even with an identical Subject.
    """
    known = [message_id for message_id in previous_message_ids if message_id]
    if not known:
        return {}
    return {'In-Reply-To': known[-1], 'References': ' '.join(known)}


def build_history_block(entries: list[HistoryEntry], conversation_url: str) -> str:
    """Quote the conversation so far, most recent first, the way a mail client does.

    The first outbound entry gets its footer back: it is the only mail that ever carried one, and
    re-rendering it here is what keeps the conversation link inside the body of every later mail.
    """
    first_outbound = next((entry for entry in entries if entry.is_outbound), None)
    blocks = []
    for entry in reversed(entries):
        body = entry.body
        if entry is first_outbound:
            body = append_conversation_footer(body, conversation_url)
        quoted = '\n'.join(f'> {line}'.rstrip() for line in body.split('\n'))
        blocks.append(f'Le {entry.sent_at}, {entry.label} a écrit :\n{quoted}')
    return '\n\n'.join(blocks)


def build_outbound_body(content: str, entries: list[HistoryEntry], conversation_url: str,
                        always_footer: bool = False) -> str:
    """Assemble an outgoing mail: the new text, the conversation link, the quoted history.

    The link is only added when the history does not already carry it — quoting it twice in the
    same mail helps nobody. `always_footer` is for the mails we mirror to the contact mailbox,
    whose whole point is to hand it the link.
    """
    history = build_history_block(entries, conversation_url)
    parts = [content] if content else []
    if always_footer or extract_conversation_uuid(history) is None:
        parts.append(conversation_footer(conversation_url))
    if history:
        parts.append(history)
    return '\n\n'.join(parts)
