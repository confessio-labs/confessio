from datetime import date, datetime

from httpx import Response
from icalendar import Calendar

from core.utils.log_utils import info
from crawling.workflows.download.google_calendar import render_events_to_html


def is_ical_response(r: Response) -> bool:
    content_type = r.headers.get('Content-Type', '')
    if content_type.lower().startswith('text/calendar'):
        return True

    # Some feeds are served with a generic content type
    return r.content[:200].lstrip().startswith(b'BEGIN:VCALENDAR')


def ical_event_to_dict(vevent) -> dict | None:
    """Convert a VEVENT into the Google Calendar API event shape that render_event expects."""
    dtstart = vevent.get('DTSTART')
    if dtstart is None:
        return None

    start_value = dtstart.dt
    if isinstance(start_value, datetime):
        start = {'dateTime': start_value.isoformat()}
    elif isinstance(start_value, date):
        start = {'date': start_value.isoformat()}
    else:
        return None

    rrule = vevent.get('RRULE')
    if isinstance(rrule, list):
        rrule = rrule[0] if rrule else None

    return {
        'summary': str(vevent.get('SUMMARY', '')),
        'location': str(vevent.get('LOCATION', '')),
        'status': str(vevent.get('STATUS', '')).lower(),
        'start': start,
        'recurrence': [f'RRULE:{rrule.to_ical().decode()}'] if rrule else [],
    }


def render_ical_to_html(content: bytes, reference_date: date | None = None) -> str | None:
    # Raw feeds can weigh tens of MB (every past event, HTML descriptions): processing them as
    # HTML takes minutes and line folding breaks their URLs, so we keep upcoming events only.
    try:
        calendar = Calendar.from_ical(content)
    except ValueError as e:
        info(f'could not parse ical content: {e}')
        return None

    events = []
    for vevent in calendar.walk('VEVENT'):
        event = ical_event_to_dict(vevent)
        if event is not None:
            events.append(event)

    html = render_events_to_html(str(calendar.get('X-WR-CALNAME', '')), events, reference_date)

    return html or None
