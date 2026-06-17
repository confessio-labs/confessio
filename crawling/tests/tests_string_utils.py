import unittest

from crawling.utils.string_utils import remove_unsafe_chars
from crawling.utils.url_utils import get_clean_full_url


class TestRemoveUnsafeChars(unittest.TestCase):
    def test_removes_nul(self):
        self.assertEqual(remove_unsafe_chars('a\x00b'), 'ab')

    def test_removes_known_unsafe_char(self):
        self.assertEqual(remove_unsafe_chars('a\udce7b'), 'ab')

    def test_keeps_newlines(self):
        self.assertEqual(remove_unsafe_chars('a\nb'), 'a\nb')

    def test_handles_none(self):
        self.assertIsNone(remove_unsafe_chars(None))

    def test_handles_empty(self):
        self.assertEqual(remove_unsafe_chars(''), '')


class TestGetCleanFullUrl(unittest.TestCase):
    def test_strips_nul_from_url(self):
        cleaned = get_clean_full_url('https://example.com/pa\x00th')
        self.assertNotIn('\x00', cleaned)
        self.assertEqual(cleaned, 'https://example.com/path')


if __name__ == '__main__':
    unittest.main()
