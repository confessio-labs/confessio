import os
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlparse, parse_qs, quote
from zoneinfo import ZoneInfo

import httpx
from icalendar.prop import vRecur

from core.utils.log_utils import info
from crawling.utils.url_utils import get_domain, MAX_URL_LENGTH

GOOGLE_CALENDAR_HOST = 'calendar.google.com'

# Google Calendar API v3. Unlike the ICS host (calendar.google.com), this endpoint is quota-keyed
# by API key rather than gated by IP reputation, so a flagged server IP is not blocked by the
# /sorry anti-bot wall. Requires a (free) API key in GOOGLE_API_KEY; the calendar must be public.
GOOGLE_CALENDAR_API_URL = 'https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events'
MAX_PAGES = 20

# One-off events are inherently dated; we only render those happening soon to keep the output
# (and therefore the resulting Pruning) reasonably stable across crawls. Recurring events carry
# no absolute date, so they stay stable.
ONE_OFF_WINDOW_DAYS = 90

PARIS_TZ = ZoneInfo('Europe/Paris')

DAY_NAMES = {
    'MO': 'lundi',
    'TU': 'mardi',
    'WE': 'mercredi',
    'TH': 'jeudi',
    'FR': 'vendredi',
    'SA': 'samedi',
    'SU': 'dimanche',
}
WEEKDAY_CODES = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']  # Monday == 0

FRENCH_MONTHS = [
    'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
    'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre',
]


############
# URL PART #
############

def is_google_calendar_url(url: str) -> bool:
    if len(url) > MAX_URL_LENGTH:
        return False

    # Raw hrefs/iframe srcs from arbitrary pages can be malformed (e.g. a bracketed WordPress
    # shortcode), and urlparse raises ValueError on those. Treat anything unparseable as "not a
    # calendar" — mirrors the guard in get_links (extract_links.py).
    try:
        return get_domain(url) == GOOGLE_CALENDAR_HOST
    except ValueError:
        return False


def get_calendar_src_ids(url: str) -> list[str]:
    # parse_qs already url-decodes the values (%40 -> @)
    return parse_qs(urlparse(url).query).get('src', [])


###############
# FETCH EVENTS #
###############

def get_api_key() -> str | None:
    return os.getenv('GOOGLE_API_KEY')


def fetch_calendar_events(calendar_id: str) -> tuple[str, list[dict]] | None:
    """Fetch a public calendar's events via the Calendar API v3. Returns (name, events) or None.

    Uses singleEvents=false so recurring events keep their RRULE (rendered as stable, date-free
    recurrence text) instead of being expanded into dated instances.
    """
    api_key = get_api_key()
    if not api_key:
        info('GOOGLE_API_KEY is not set, cannot fetch google calendar events')
        return None

    # Lazy import to avoid a circular import (download_content imports this module)
    from crawling.workflows.download.download_content import get_headers, TIMEOUT

    api_url = GOOGLE_CALENDAR_API_URL.format(calendar_id=quote(calendar_id, safe=''))
    params = {
        'key': api_key,
        'singleEvents': 'false',
        'showDeleted': 'false',
        'maxResults': 2500,
    }

    calendar_name = ''
    events: list[dict] = []
    page_token = None
    for i in range(MAX_PAGES):
        if page_token:
            params['pageToken'] = page_token

        info(f'getting google calendar events for {calendar_id} (page {i + 1}/{MAX_PAGES})')
        try:
            with httpx.Client() as client:
                r = client.get(api_url, params=params, headers=get_headers(), timeout=TIMEOUT)
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            info(e)
            return None

        if r.status_code != 200:
            info(f'got status code {r.status_code} for google calendar {calendar_id}: '
                 f'{r.text[:200]}')
            return None

        data = r.json()
        calendar_name = data.get('summary', calendar_name)
        events.extend(data.get('items', []))

        page_token = data.get('nextPageToken')
        if not page_token:
            break
    else:
        info(f'reached max {MAX_PAGES} pages for google calendar {calendar_id}, '
             f'events may be truncated')

    return calendar_name, events


def get_google_calendar_html(url: str) -> str | None:
    src_ids = get_calendar_src_ids(url)
    if not src_ids:
        return None

    reference_date = datetime.now(PARIS_TZ).date()

    html_parts = []
    for src_id in src_ids:
        result = fetch_calendar_events(src_id)
        if result is None:
            continue
        calendar_name, events = result
        html = render_events_to_html(calendar_name, events, reference_date)
        if html:
            html_parts.append(html)

    if not html_parts:
        return None

    return '\n'.join(html_parts)


###########
# RENDER  #
###########

def to_paris(value: date):
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(PARIS_TZ)
    return value


def render_time(start) -> str:
    if not isinstance(start, datetime):
        return ''  # all-day event, no time to render
    return f' à {start.hour}h{start.minute:02d}'


def day_name(value: date) -> str:
    return DAY_NAMES[WEEKDAY_CODES[value.weekday()]]


def parse_byday(entry) -> tuple[int | None, str | None]:
    # 'SA' -> (None, 'SA'); '3TH' -> (3, 'TH'); '-1SU' -> (-1, 'SU')
    match = re.fullmatch(r'([+-]?\d+)?([A-Z]{2})', str(entry))
    if not match:
        return None, None
    return (int(match.group(1)) if match.group(1) else None), match.group(2)


def ordinal_fr(ordinal: int) -> str:
    if ordinal == -1:
        return 'dernier'
    if ordinal == 1:
        return '1er'
    return f'{ordinal}e'


def format_weekly_days(day_names: list[str]) -> str:
    plural = [f'{d}s' for d in day_names]
    if len(plural) == 1:
        return f'les {plural[0]}'
    return 'les ' + ', '.join(plural[:-1]) + f' et {plural[-1]}'


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def render_recurrence(rrule, start) -> str | None:
    freq = _first(rrule.get('FREQ'))
    time_str = render_time(start)
    bydays = rrule.get('BYDAY') or []

    if freq == 'WEEKLY':
        codes = [parse_byday(b)[1] for b in bydays]
        day_names = [DAY_NAMES[c] for c in codes if c in DAY_NAMES]
        if not day_names:
            day_names = [day_name(start)]
        return f'tous {format_weekly_days(day_names)}{time_str}'

    if freq == 'DAILY':
        return f'tous les jours{time_str}'

    if freq == 'MONTHLY':
        if bydays:
            ordinal, code = parse_byday(bydays[0])
            if code in DAY_NAMES and ordinal is not None:
                return f'le {ordinal_fr(ordinal)} {DAY_NAMES[code]} du mois{time_str}'
        return f'le {start.day} de chaque mois{time_str}'

    # Unknown/other frequency: fall back to the start day of week
    return f'{day_name(start)}{time_str}'


def render_one_off(start) -> str:
    event_date = start.date() if isinstance(start, datetime) else start
    return (f'{day_name(event_date)} {event_date.day} {FRENCH_MONTHS[event_date.month - 1]} '
            f'{event_date.year}{render_time(start)}')


def parse_event_start(start: dict | None):
    if not start:
        return None
    if start.get('dateTime'):
        return to_paris(datetime.fromisoformat(start['dateTime']))
    if start.get('date'):
        return date.fromisoformat(start['date'])
    return None


def get_rrule(event: dict) -> vRecur | None:
    for line in event.get('recurrence') or []:
        if str(line).upper().startswith('RRULE:'):
            return vRecur.from_ical(str(line)[len('RRULE:'):])
    return None


def render_event(event: dict, reference_date: date) -> str | None:
    if event.get('status') == 'cancelled':
        return None

    start = parse_event_start(event.get('start'))
    if start is None:
        return None

    rrule = get_rrule(event)
    if rrule:
        until = _first(rrule.get('UNTIL'))
        if until is not None:
            until_date = until.date() if isinstance(until, datetime) else until
            if until_date < reference_date:
                return None  # recurrence has ended
        when = render_recurrence(rrule, start)
    else:
        event_date = start.date() if isinstance(start, datetime) else start
        if event_date < reference_date or event_date > reference_date + timedelta(
                days=ONE_OFF_WINDOW_DAYS):
            return None  # past or too far in the future
        when = render_one_off(start)

    if when is None:
        return None

    summary = (event.get('summary') or '').strip()
    location = (event.get('location') or '').strip()
    parts = [p for p in [summary, when, location] if p]
    return ' — '.join(parts)


def render_events_to_html(calendar_name: str, events: list[dict],
                          reference_date: date | None = None) -> str:
    if reference_date is None:
        reference_date = datetime.now(PARIS_TZ).date()

    lines = []
    for event in events:
        rendered = render_event(event, reference_date)
        if rendered:
            lines.append(f'<p>{rendered}</p>')

    if not lines:
        return ''

    name = (calendar_name or '').strip()
    header = f'<h2>{name}</h2>\n' if name else ''
    return header + '\n'.join(lines)


if __name__ == '__main__':
    url_ = ('https://calendar.google.com/calendar/embed'
            '?src=notredamedurocher%40gmail.com&ctz=Europe%2FParis')
    print(url_)
    print(get_google_calendar_html(url_))
