import json
import os
import unittest

from crawling.workflows.crawl.extract_links import parse_content_links
from crawling.workflows.download.download_content import get_domain


class TestExtractLinks(unittest.TestCase):
    @staticmethod
    def parse_content_links_fixtures():
        return [
            ('https://www.eglise-saintgermaindespres.fr/', 'st-germain-des-pres', []),
            ('https://paroissesaintbruno.pagesperso-orange.fr/', 'st-bruno-des-chartreux', []),
            ('https://saintleusaintgilles.fr/', 'st-leu-st-gilles', []),
            ('http://paroisse.ndchoisille.free.fr/', 'ndchoisille', []),
            ('https://paroisses-pays-auray.fr', 'auray', ['/pluvigner', '/accueil-plougoumelen']),
            ('https://paroisses-pays-auray.fr/pluvigner', 'pluvigner',
             ['', '/accueil-plougoumelen']),
        ]

    def test_parse_content_links(self):
        tests_dir = os.path.dirname(os.path.realpath(__file__))
        for home_url, file_name, forbidden_outer_paths in self.parse_content_links_fixtures():
            with self.subTest():
                with open(f'{tests_dir}/fixtures/urls/{file_name}.html') as f:
                    lines = f.readlines()
                with open(f'{tests_dir}/fixtures/urls/{file_name}.json') as f:
                    expected_links = json.load(f)
                content = ''.join(lines)
                links = parse_content_links(content, home_url, {get_domain(home_url)},
                                            set(forbidden_outer_paths), {}, set())
                # print(json.dumps(list(links), indent=2))
                self.assertSetEqual(set(links), set(expected_links), f'Failed for {file_name}')


if __name__ == '__main__':
    unittest.main()
