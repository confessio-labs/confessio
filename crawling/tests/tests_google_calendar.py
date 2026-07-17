import json
import os
import unittest
from datetime import date

from crawling.workflows.crawl.extract_widgets import detect_google_calendar_urls, parse_html
from crawling.workflows.download.google_calendar import is_google_calendar_url, \
    get_calendar_src_ids, render_events_to_html

EMBED_URL = ('https://calendar.google.com/calendar/embed'
             '?src=notredamedurocher%40gmail.com&ctz=Europe%2FParis')

REFERENCE_DATE = date(2026, 3, 1)


class TestGoogleCalendar(unittest.TestCase):
    @staticmethod
    def load_events_fixture() -> dict:
        tests_dir = os.path.dirname(os.path.realpath(__file__))
        with open(f'{tests_dir}/fixtures/google_calendar/events.json') as f:
            return json.load(f)

    def test_is_google_calendar_url(self):
        self.assertTrue(is_google_calendar_url(EMBED_URL))
        self.assertTrue(is_google_calendar_url(
            'https://calendar.google.com/calendar/u/0/newembed'
            '?src=abc%40group.calendar.google.com'))
        self.assertFalse(is_google_calendar_url('https://www.paroisse-biarritz.fr/'))
        self.assertFalse(is_google_calendar_url('https://www.google.com/calendar'))

    def test_is_google_calendar_url_malformed(self):
        # urlparse raises ValueError on a bracketed-but-invalid netloc; must not crawl-crash.
        self.assertFalse(
            is_google_calendar_url('http://[saint-du-jour date=false messe=true texte=true]'))

    def test_get_calendar_src_ids(self):
        self.assertEqual(get_calendar_src_ids(EMBED_URL), ['notredamedurocher@gmail.com'])

    def test_get_calendar_src_ids_multiple(self):
        url = ('https://calendar.google.com/calendar/embed'
               '?src=one%40gmail.com&src=two%40group.calendar.google.com')
        self.assertEqual(get_calendar_src_ids(url),
                         ['one@gmail.com', 'two@group.calendar.google.com'])

    def test_get_calendar_src_ids_none(self):
        self.assertEqual(get_calendar_src_ids('https://calendar.google.com/calendar/embed'), [])

    def test_detect_google_calendar_urls_iframe_and_anchor(self):
        html = f'''<html><body>
            <iframe src="{EMBED_URL}"></iframe>
            <a href="{EMBED_URL}">Voir l'agenda</a>
            <a href="https://www.facebook.com/page">Facebook</a>
        </body></html>'''
        self.assertEqual(detect_google_calendar_urls(parse_html(html)), {EMBED_URL})

    def test_detect_google_calendar_urls_none(self):
        html = '<html><body><a href="/horaires">Horaires</a></body></html>'
        self.assertEqual(detect_google_calendar_urls(parse_html(html)), set())

    def test_detect_google_calendar_urls_malformed_href(self):
        # A malformed href on the page must not crash the whole crawl.
        html = ('<html><body>'
                '<a href="http://[saint-du-jour date=false messe=true texte=true]">x</a>'
                '</body></html>')
        self.assertEqual(detect_google_calendar_urls(parse_html(html)), set())

    def test_render_events_to_html(self):
        data = self.load_events_fixture()

        result = render_events_to_html(data['summary'], data['items'],
                                       reference_date=REFERENCE_DATE)
        expected = (
            '<h2>Paroisse Test</h2>\n'
            '<p>Confessions — tous les samedis à 17h00 — Saint-Martin</p>\n'
            '<p>Groupe de louange — le 3e jeudi du mois à 20h00</p>\n'
            '<p>Oraison — tous les mardis, mercredis, jeudis et vendredis à 7h00</p>\n'
            '<p>Fete patronale — vendredi 20 mars 2026</p>\n'
            '<p>Confessions avant Paques — vendredi 20 mars 2026 à 9h30</p>\n'
            '<p>Vigile pascale — samedi 4 avril 2026 à 21h00</p>\n'
            '<p>Messe de Paques — dimanche 5 avril 2026 à 10h30</p>'
        )
        self.assertEqual(result, expected)

    def test_render_events_to_html_order_is_independent_of_input_order(self):
        # Google's paging order is unspecified; it must never leak into the hashed output.
        items = self.load_events_fixture()['items']

        self.assertEqual(render_events_to_html('Paroisse Test', items,
                                               reference_date=REFERENCE_DATE),
                         render_events_to_html('Paroisse Test', list(reversed(items)),
                                               reference_date=REFERENCE_DATE))

    def test_render_events_to_html_empty(self):
        self.assertEqual(render_events_to_html('Paroisse Test', []), '')


if __name__ == '__main__':
    unittest.main()
