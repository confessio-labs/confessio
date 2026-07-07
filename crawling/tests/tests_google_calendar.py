import os
import unittest
from datetime import date

from crawling.workflows.crawl.extract_widgets import detect_google_calendar_urls
from crawling.workflows.download.google_calendar import is_google_calendar_url, get_ics_urls, \
    render_ics_to_html

EMBED_URL = ('https://calendar.google.com/calendar/embed'
             '?src=notredamedurocher%40gmail.com&ctz=Europe%2FParis')


class TestGoogleCalendar(unittest.TestCase):
    def test_is_google_calendar_url(self):
        self.assertTrue(is_google_calendar_url(EMBED_URL))
        self.assertTrue(is_google_calendar_url(
            'https://calendar.google.com/calendar/u/0/newembed'
            '?src=abc%40group.calendar.google.com'))
        self.assertFalse(is_google_calendar_url('https://www.paroisse-biarritz.fr/'))
        self.assertFalse(is_google_calendar_url('https://www.google.com/calendar'))

    def test_get_ics_urls(self):
        self.assertEqual(
            get_ics_urls(EMBED_URL),
            ['https://calendar.google.com/calendar/ical/'
             'notredamedurocher%40gmail.com/public/basic.ics'],
        )

    def test_get_ics_urls_multiple_src(self):
        url = ('https://calendar.google.com/calendar/embed'
               '?src=one%40gmail.com&src=two%40group.calendar.google.com')
        self.assertEqual(
            get_ics_urls(url),
            ['https://calendar.google.com/calendar/ical/one%40gmail.com/public/basic.ics',
             'https://calendar.google.com/calendar/ical/'
             'two%40group.calendar.google.com/public/basic.ics'],
        )

    def test_get_ics_urls_no_src(self):
        self.assertEqual(get_ics_urls('https://calendar.google.com/calendar/embed'), [])

    def test_detect_google_calendar_urls_iframe_and_anchor(self):
        html = f'''<html><body>
            <iframe src="{EMBED_URL}"></iframe>
            <a href="{EMBED_URL}">Voir l'agenda</a>
            <a href="https://www.facebook.com/page">Facebook</a>
        </body></html>'''
        self.assertEqual(detect_google_calendar_urls(html), {EMBED_URL})

    def test_detect_google_calendar_urls_none(self):
        html = '<html><body><a href="/horaires">Horaires</a></body></html>'
        self.assertEqual(detect_google_calendar_urls(html), set())

    def test_render_ics_to_html(self):
        tests_dir = os.path.dirname(os.path.realpath(__file__))
        with open(f'{tests_dir}/fixtures/google_calendar/sample.ics') as f:
            ics_content = f.read()

        result = render_ics_to_html(ics_content, reference_date=date(2026, 3, 1))
        expected = (
            '<h2>Paroisse Test</h2>\n'
            '<p>Confessions — tous les samedis à 17h00 — Saint-Martin</p>\n'
            '<p>Groupe de louange — le 3e jeudi du mois à 20h00</p>\n'
            '<p>Oraison — tous les mardis, mercredis, jeudis et vendredis à 7h00</p>\n'
            '<p>Confessions avant Paques — vendredi 20 mars 2026 à 9h30</p>'
        )
        self.assertEqual(result, expected)

    def test_render_ics_to_html_invalid(self):
        self.assertEqual(render_ics_to_html('not an ics file'), '')


if __name__ == '__main__':
    unittest.main()
