"""Pure helpers for the admin messaging: no ORM, no service imports, so they stay in the fast
unit-test suite.

Threading is carried by the conversation link we append to every outgoing body. Mailgun drops
everything below a `--` signature delimiter from `stripped-text`, so the footer stays invisible in
what we display, while `body-plain` keeps it — which is exactly where we read the uuid back from
when the correspondent replies with our message quoted.
"""
import re
from email.utils import parseaddr

FOOTER_LABEL = 'Conversation'

_UUID = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
# Match the link, not a bare uuid: an unrelated uuid quoted in the mail must not hijack the thread.
CONVERSATION_LINK_RE = re.compile(rf'/messaging/({_UUID})')

# Senders we never open a conversation for: bounces and auto-responders have nobody to reply to.
AUTOMATED_LOCAL_PARTS = ('mailer-daemon', 'postmaster')


def append_conversation_footer(body: str, conversation_url: str) -> str:
    return f'{body}\n\n--\n{FOOTER_LABEL} : {conversation_url}'


def extract_conversation_uuid(*texts: str) -> str | None:
    """Find the conversation uuid in the first text that carries our footer link."""
    for text in texts:
        if not text:
            continue
        match = CONVERSATION_LINK_RE.search(text)
        if match:
            return match.group(1)
    return None


def parse_sender(reply_to: str, from_header: str) -> tuple[str, str]:
    """Who are we talking to? Reply-To wins over From, as standard mail semantics require.

    This is what recovers the visitor's real address on a contact-form mail: SES only accepts a
    verified identity as From, so we send those from no-reply@ with the visitor in Reply-To.
    """
    for header in (reply_to, from_header):
        name, email = parseaddr(header or '')
        # parseaddr never fails: it hands back the raw string as the address when it cannot parse
        # one ('garbage' -> ('', 'garbage')). Require an @ so a malformed header falls through
        # instead of becoming a conversation we could never mail back to.
        if '@' in email:
            return name, email
    return '', ''


def is_automated_sender(email: str) -> bool:
    local_part = email.split('@')[0].lower()
    return local_part in AUTOMATED_LOCAL_PARTS


def build_reply_subject(subject: str, is_first: bool) -> str:
    if is_first or subject.lower().startswith('re:'):
        return subject
    return f'Re: {subject}'
