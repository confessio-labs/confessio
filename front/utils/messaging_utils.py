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
from email.utils import getaddresses, parseaddr
from html import escape

FOOTER_INTRO = "Ce message est traité par l'équipe de"
FOOTER_LABEL = 'Espace administrateur'

# Inlined: mail clients drop <style> blocks, and the footer must read as an aside, not as content.
FOOTER_STYLE = 'color:#888888;font-size:13px;line-height:1.5;margin:4px 0'
ATTRIBUTION_STYLE = 'color:#666666;font-size:13px;margin:16px 0 4px'
QUOTE_STYLE = ('border-left:2px solid #cccccc;margin:0;padding-left:12px;color:#555555')

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


def conversation_footer(conversation_url: str, home_url: str) -> str:
    """The plain-text footer. The leading `--` is load-bearing: Mailgun drops everything below it
    from stripped-text, which is what keeps the footer out of the bodies we display, and the bare
    conversation URL is what we read the thread key back from."""
    return (f'--\n'
            f'{FOOTER_INTRO} Confessio : {home_url}\n'
            f'\n'
            f'{FOOTER_LABEL} :\n'
            f'{conversation_url}')


def conversation_footer_html(conversation_url: str, home_url: str) -> str:
    """The same footer for the HTML part: greyed out, both links carried by their words.

    Hiding the admin URL behind a word costs nothing on the way back: a reply quotes our markup,
    and the href survives in `body-html`, which is one of the texts we search the thread key in.
    """
    return (f'<p style="{FOOTER_STYLE}">{FOOTER_INTRO} '
            f'<a href="{escape(home_url, quote=True)}" style="color:#888888">Confessio</a>.</p>'
            f'<p style="{FOOTER_STYLE}">'
            f'<a href="{escape(conversation_url, quote=True)}" style="color:#888888">'
            f'{FOOTER_LABEL}</a></p>')


def append_conversation_footer(body: str, conversation_url: str, home_url: str) -> str:
    return f'{body}\n\n{conversation_footer(conversation_url, home_url)}'


def html_paragraphs(text: str) -> str:
    """Turn a plain-text block into paragraphs: one <p> per blank line, <br> inside.

    Everything is escaped — these bodies come from mail we received, and none of it is markup we
    wrote.
    """
    blocks = [block for block in re.split(r'\n\s*\n', text.strip()) if block.strip()]
    return ''.join('<p>' + '<br>'.join(escape(line) for line in block.split('\n')) + '</p>'
                   for block in blocks)


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


def first_external_address(header: str, ours: tuple[str, ...]) -> tuple[str, str]:
    """The correspondent among a mail's recipients, skipping our own addresses.

    A reply copied to the archive address lists it alongside the person it answers; opening a
    conversation on our own mailbox would be a conversation talking to itself.
    """
    for name, email in getaddresses([header or '']):
        if '@' in email and not any(is_same_email(email, one) for one in ours):
            return name, email
    return '', ''


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


def build_history_block(entries: list[HistoryEntry], conversation_url: str,
                        home_url: str) -> str:
    """Quote the conversation so far, most recent first, the way a mail client does.

    The first outbound entry gets its footer back: it is the only mail that ever carried one, and
    re-rendering it here is what keeps the conversation link inside the body of every later mail.
    """
    first_outbound = next((entry for entry in entries if entry.is_outbound), None)
    blocks = []
    for entry in reversed(entries):
        body = entry.body
        if entry is first_outbound:
            body = append_conversation_footer(body, conversation_url, home_url)
        quoted = '\n'.join(f'> {line}'.rstrip() for line in body.split('\n'))
        blocks.append(f'Le {entry.sent_at}, {entry.label} a écrit :\n{quoted}')
    return '\n\n'.join(blocks)


def build_history_block_html(entries: list[HistoryEntry], conversation_url: str,
                             home_url: str) -> str:
    """The same history for the HTML part, each message in its own blockquote."""
    first_outbound = next((entry for entry in entries if entry.is_outbound), None)
    blocks = []
    for entry in reversed(entries):
        quoted = html_paragraphs(entry.body)
        if entry is first_outbound:
            quoted += conversation_footer_html(conversation_url, home_url)
        blocks.append(f'<p style="{ATTRIBUTION_STYLE}">Le {escape(entry.sent_at)}, '
                      f'{escape(entry.label)} a écrit :</p>'
                      f'<blockquote style="{QUOTE_STYLE}">{quoted}</blockquote>')
    return ''.join(blocks)


def build_outbound_bodies(content: str, entries: list[HistoryEntry], conversation_url: str,
                          home_url: str, always_footer: bool = False) -> tuple[str, str]:
    """Assemble one outgoing mail, text part first, HTML part second.

    Both carry the same thing in the same order — the new text, the conversation link, the quoted
    history — and the footer decision is taken once so the two parts can never disagree. The link
    is only added when the history does not already carry it; `always_footer` is for the mails we
    mirror to the contact mailbox, whose whole point is to hand it that link.
    """
    history = build_history_block(entries, conversation_url, home_url)
    with_footer = always_footer or extract_conversation_uuid(history) is None

    parts = [content] if content else []
    if with_footer:
        parts.append(conversation_footer(conversation_url, home_url))
    if history:
        parts.append(history)

    html = html_paragraphs(content) if content else ''
    if with_footer:
        html += '<hr style="border:none;border-top:1px solid #dddddd;margin:16px 0">'
        html += conversation_footer_html(conversation_url, home_url)
    html += build_history_block_html(entries, conversation_url, home_url)

    return '\n\n'.join(parts), html
