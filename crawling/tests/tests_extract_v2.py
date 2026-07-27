import os
import unittest

from crawling.workflows.scrape.download_refine_and_extract import get_extracted_v2_html_list


class MyTestCase(unittest.TestCase):
    @staticmethod
    def get_paragraphs_fixtures():
        return [
            'chaville',
            'mock1',
            'mock2',
            'maisons-laffitte',
            'maisons-laffitte2',
            'ste-jeanne-darc',
            'st-jacques-du-haut-pas',
            'st-bruno-des-chartreux',
            'st-bruno-des-chartreux2',
            'amplepuis',
            'ntre-dame-de-lassomption',
            'ntre-dame-des-lumieres',
            'ntre-dame-des-lumieres2',
            'st-bonaventure',
            'st-nomdejesus',
            'fourviere',
            'cdde',
            'vaise',
            'vaise2',
            'ferreol',
            'smdv',
            'st-alexandre',
            'rambouillet',
            'voisins',
            'houilles',
            'caluire',
            'stebathilde',
            'stbenoit',
            'stgermain',
            'immaculee-conception',
            'sjsc',
            'madeleine',
            'bjmm',
            'paroissesaintpauldelalys',
        ]

    def test_extract(self):
        tests_dir = os.path.dirname(os.path.realpath(__file__))
        for file_name in self.get_paragraphs_fixtures():
            with self.subTest():
                with open(f'{tests_dir}/fixtures/extract_v2/{file_name}.html') as f:
                    lines = f.readlines()
                with open(f'{tests_dir}/fixtures/extract_v2/{file_name}.txt') as f:
                    expected_lines = f.readlines()
                content_html = ''.join(lines)
                expected_confession_part = ''.join(expected_lines)

                confession_parts = get_extracted_v2_html_list(content_html)
                confession_part = '\n\n'.join(confession_parts) if confession_parts else None
                # print(confession_part)

                if not expected_confession_part:
                    self.assertIsNone(confession_part, msg=file_name)
                else:
                    self.maxDiff = None
                    self.assertEqual(expected_confession_part, confession_part, msg=file_name)


if __name__ == '__main__':
    unittest.main()
