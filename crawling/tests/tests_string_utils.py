import unittest

from crawling.utils.string_utils import remove_unsafe_chars, strip_null_bytes
from crawling.utils.url_utils import get_clean_full_url


class TestStripNullBytes(unittest.TestCase):
    def test_strips_from_plain_string(self):
        self.assertEqual(strip_null_bytes('a\x00b'), 'ab')

    def test_strips_known_surrogate(self):
        self.assertEqual(strip_null_bytes('a\udce7b'), 'ab')

    def test_recurses_into_dict_values_and_keys(self):
        self.assertEqual(
            strip_null_bytes({'qu\x00ery': 'presbyt\x00ere'}),
            {'query': 'presbytere'},
        )

    def test_recurses_into_nested_lists(self):
        self.assertEqual(
            strip_null_bytes({'rows': [['a\x00', 'b'], ['c']]}),
            {'rows': [['a', 'b'], ['c']]},
        )

    def test_preserves_non_string_scalars(self):
        value = {'n': 1, 'f': 1.5, 'ok': True, 'nothing': None}
        self.assertEqual(strip_null_bytes(value), value)

    def test_tuple_becomes_list(self):
        self.assertEqual(strip_null_bytes(('a\x00', 'b')), ['a', 'b'])


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
