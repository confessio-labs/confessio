import unittest

from crawling.utils.url_utils import path_key, select_next_link_to_visit


class TestPathKey(unittest.TestCase):
    def test_trailing_slash_is_normalized(self):
        self.assertEqual(path_key('https://ex.com/a/'), path_key('https://ex.com/a'))

    def test_query_string_is_ignored(self):
        self.assertEqual(path_key('https://ex.com/a/?pays=NL'), path_key('https://ex.com/a'))


class TestSelectNextLinkToVisit(unittest.TestCase):
    HOME = 'https://ex.com'
    HORAIRES = 'https://ex.com/informations-pratiques/horaires/'
    PRIERE = 'https://ex.com/priere-a-marie/'
    VARIANTS = [
        'https://ex.com/faire-pelerinage/liste-pelerinages-annonces/?pays=NL',
        'https://ex.com/faire-pelerinage/liste-pelerinages-annonces/?pays=BE',
        'https://ex.com/faire-pelerinage/liste-pelerinages-annonces/?pays=US',
        'https://ex.com/faire-pelerinage/liste-pelerinages-annonces/?pays=FR',
        'https://ex.com/faire-pelerinage/liste-pelerinages-annonces/?pays=DE',
    ]

    @staticmethod
    def drain(initial_links):
        # dict as an ordered set, mirroring links_to_visit in search_for_confession_pages
        queue = dict.fromkeys(initial_links)
        visited = set()
        order = []
        while queue:
            link = select_next_link_to_visit(queue, visited)
            order.append(link)
            del queue[link]
            visited.add(link)
        return order

    def test_unique_paths_visited_before_variants(self):
        order = self.drain([self.HOME, *self.VARIANTS, self.HORAIRES, self.PRIERE])
        first_variant = min(order.index(v) for v in self.VARIANTS)
        for unique_link in (self.HOME, self.HORAIRES, self.PRIERE):
            self.assertLess(order.index(unique_link), first_variant)

    def test_variants_drained_in_fifo_order(self):
        order = self.drain([self.HOME, *self.VARIANTS, self.HORAIRES, self.PRIERE])
        variant_set = set(self.VARIANTS)
        drained_variants = [link for link in order if link in variant_set]
        self.assertEqual(drained_variants, self.VARIANTS)

    def test_two_large_groups_are_interleaved_round_robin(self):
        # Reproduces the agenda-vs-pelerinage case: neither group should be fully drained before
        # the other is touched — they must alternate one page at a time.
        agenda = [f'https://ex.com/agenda/?mois=m{i}' for i in range(4)]
        pel = [f'https://ex.com/faire-pelerinage/liste/?pays=p{i}' for i in range(5)]
        order = self.drain([*agenda, *pel])
        paths = [path_key(link) for link in order]
        # first two visits cover BOTH distinct paths, not two of the same
        self.assertEqual({paths[0], paths[1]}, {path_key(agenda[0]), path_key(pel[0])})
        # the two groups keep alternating until the smaller one is exhausted
        self.assertEqual(paths[:8], [path_key(agenda[0]), path_key(pel[0])] * 4)


if __name__ == '__main__':
    unittest.main()
