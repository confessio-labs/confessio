import unittest
from datetime import date

from httpx import Response

from crawling.workflows.download.ical_calendar import is_ical_response, render_ical_to_html

REFERENCE_DATE = date(2026, 3, 1)


def build_ical(*events: list[str], calendar_name: str | None = 'Paroisse Test') -> bytes:
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Test//EN']
    if calendar_name:
        lines.append(f'X-WR-CALNAME:{calendar_name}')
    for i, event_lines in enumerate(events):
        lines += ['BEGIN:VEVENT', f'UID:event-{i}@test', 'DTSTAMP:20260101T000000Z']
        lines += event_lines
        lines.append('END:VEVENT')
    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines).encode('utf-8')


UPCOMING_CONFESSIONS = [
    'SUMMARY:Confessions avant Pâques',
    'DTSTART;TZID=Europe/Paris:20260320T093000',
    # Folded line, as feeds wrap long properties at 75 octets
    'LOCATION:Église Saint-',
    ' Martin',
]
WEEKLY_CONFESSIONS = [
    'SUMMARY:Confessions',
    'DTSTART;TZID=Europe/Paris:20250906T170000',
    'RRULE:FREQ=WEEKLY;BYDAY=SA',
]
ALL_DAY = [
    'SUMMARY:Fête de saint Joseph',
    'DTSTART;VALUE=DATE:20260319',
]
UTC_EVENT = [
    'SUMMARY:Vigile pascale',
    'DTSTART:20260404T190000Z',
]
PAST_EVENT = [
    'SUMMARY:Messe passée',
    'DTSTART;TZID=Europe/Paris:20260215T100000',
]
FAR_FUTURE_EVENT = [
    'SUMMARY:Pèlerinage',
    'DTSTART;TZID=Europe/Paris:20260701T100000',
]
EXPIRED_SERIES = [
    'SUMMARY:Confessions de Carême 2020',
    'DTSTART;TZID=Europe/Paris:20200301T170000',
    'RRULE:FREQ=WEEKLY;COUNT=5;BYDAY=SU',
]
CANCELLED_EVENT = [
    'SUMMARY:Concert annulé',
    'DTSTART;TZID=Europe/Paris:20260310T180000',
    'STATUS:CANCELLED',
]


class TestIcalCalendar(unittest.TestCase):
    def test_render_ical_to_html(self):
        content = build_ical(UPCOMING_CONFESSIONS, WEEKLY_CONFESSIONS, ALL_DAY, UTC_EVENT,
                             PAST_EVENT, FAR_FUTURE_EVENT, EXPIRED_SERIES, CANCELLED_EVENT)

        expected = (
            '<h2>Paroisse Test</h2>\n'
            '<p>Confessions — tous les samedis à 17h00</p>\n'
            '<p>Fête de saint Joseph — jeudi 19 mars 2026</p>\n'
            '<p>Confessions avant Pâques — vendredi 20 mars 2026 à 9h30 — Église Saint-Martin</p>\n'
            '<p>Vigile pascale — samedi 4 avril 2026 à 21h00</p>'
        )
        self.assertEqual(render_ical_to_html(content, REFERENCE_DATE), expected)

    def test_render_ical_to_html_without_calendar_name(self):
        content = build_ical(ALL_DAY, calendar_name=None)

        self.assertEqual(render_ical_to_html(content, REFERENCE_DATE),
                         '<p>Fête de saint Joseph — jeudi 19 mars 2026</p>')

    def test_render_ical_to_html_no_upcoming_event(self):
        content = build_ical(PAST_EVENT, FAR_FUTURE_EVENT, EXPIRED_SERIES, CANCELLED_EVENT)

        self.assertIsNone(render_ical_to_html(content, REFERENCE_DATE))

    def test_render_ical_to_html_malformed(self):
        self.assertIsNone(render_ical_to_html(b'<html><body>Not a calendar</body></html>',
                                              REFERENCE_DATE))

    def test_is_ical_response(self):
        content = build_ical(ALL_DAY)

        self.assertTrue(is_ical_response(Response(
            200, headers={'Content-Type': 'text/calendar; charset=utf-8'}, content=content)))
        self.assertTrue(is_ical_response(Response(
            200, headers={'Content-Type': 'text/plain'}, content=b'\r\n' + content)))
        self.assertFalse(is_ical_response(Response(
            200, headers={'Content-Type': 'text/html; charset=utf-8'},
            content=b'<html><body>BEGIN:VCALENDAR</body></html>')))


if __name__ == '__main__':
    unittest.main()
