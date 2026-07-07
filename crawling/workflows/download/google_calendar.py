import re
from datetime import date, datetime, timedelta
from urllib.parse import urlparse, parse_qs, quote
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar

from core.utils.log_utils import info
from crawling.utils.url_utils import get_domain

GOOGLE_CALENDAR_HOST = 'calendar.google.com'

# Public iCalendar feed of a Google Calendar, e.g.
# https://calendar.google.com/calendar/ical/xxx%40gmail.com/public/basic.ics
ICS_URL_TEMPLATE = 'https://' + GOOGLE_CALENDAR_HOST + '/calendar/ical/{src}/public/basic.ics'

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
    return get_domain(url) == GOOGLE_CALENDAR_HOST


def get_calendar_src_ids(url: str) -> list[str]:
    # parse_qs already url-decodes the values (%40 -> @)
    return parse_qs(urlparse(url).query).get('src', [])


def get_ics_urls(url: str) -> list[str]:
    # quote re-encodes the calendar id so '@' becomes '%40' in the ical path
    return [ICS_URL_TEMPLATE.format(src=quote(src, safe='')) for src in get_calendar_src_ids(url)]


#############
# FETCH ICS #
#############

def fetch_ics(ics_url: str) -> str | None:
    # Lazy import to avoid a circular import (download_content imports this module)
    from crawling.workflows.download.download_content import get_headers, TIMEOUT

    info(f'getting ics content from url {ics_url}')
    try:
        with httpx.Client() as client:
            r = client.get(ics_url, headers=get_headers(), timeout=TIMEOUT, follow_redirects=True)
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        info(e)
        return None

    if r.status_code != 200:
        info(f'got status code {r.status_code} for ics url {ics_url}')
        return None

    return r.text


def get_google_calendar_html(url: str) -> str | None:
    ics_urls = get_ics_urls(url)
    if not ics_urls:
        return None

    html_parts = []
    for ics_url in ics_urls:
        ics_content = fetch_ics(ics_url)
        if ics_content is None:
            continue
        html = render_ics_to_html(ics_content)
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


def parse_byday(entry: str) -> tuple[int | None, str | None]:
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


def render_event(event, reference_date: date) -> str | None:
    dtstart = event.get('DTSTART')
    if dtstart is None:
        return None
    start = to_paris(dtstart.dt)

    rrule = event.get('RRULE')
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

    summary = str(event.get('SUMMARY', '')).strip()
    location = str(event.get('LOCATION', '')).strip()
    parts = [p for p in [summary, when, location] if p]
    return ' — '.join(parts)


def render_ics_to_html(ics_content: str, reference_date: date | None = None) -> str:
    if reference_date is None:
        reference_date = datetime.now(PARIS_TZ).date()

    try:
        calendar = Calendar.from_ical(ics_content)
    except Exception as e:
        info(e)
        return ''

    lines = []
    for event in calendar.walk('VEVENT'):
        rendered = render_event(event, reference_date)
        if rendered:
            lines.append(f'<p>{rendered}</p>')

    if not lines:
        return ''

    calendar_name = str(calendar.get('X-WR-CALNAME', '')).strip()
    header = f'<h2>{calendar_name}</h2>\n' if calendar_name else ''
    return header + '\n'.join(lines)


if __name__ == '__main__':
    url_ = ('https://calendar.google.com/calendar/embed'
            '?src=notredamedurocher%40gmail.com&ctz=Europe%2FParis')
    print(url_)
    print(get_google_calendar_html(url_))
