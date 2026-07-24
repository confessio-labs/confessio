import json
import os
import unittest

from registry.utils.overpass_utils import build_admin_centre_query, parse_admin_centres


class TestOverpassUtils(unittest.TestCase):
    @staticmethod
    def load_fixture():
        tests_dir = os.path.dirname(os.path.realpath(__file__))
        with open(f'{tests_dir}/fixtures/overpass_admin_centres.json') as f:
            return json.load(f)

    def test_build_admin_centre_query(self):
        query = build_admin_centre_query('44')
        self.assertIn('["ref:INSEE"~"^44"]', query)
        self.assertIn('admin_centre', query)

    def test_parse_admin_centres(self):
        admin_centres = parse_admin_centres(self.load_fixture())
        self.assertEqual(admin_centres, {
            # latitude first, longitude second
            '44155': (47.0098098, -1.5833651),
            # falls back to the label node when there is no admin_centre
            '44001': (47.1, -1.1),
            # prefers admin_centre over label whatever the member order
            '44002': (47.3, -1.3),
            # 44003 (no node member), 44004 (node absent from payload) and the relation
            # without ref:INSEE are skipped
        })

    def test_parse_empty_response(self):
        self.assertEqual(parse_admin_centres({}), {})
        self.assertEqual(parse_admin_centres({'elements': []}), {})
