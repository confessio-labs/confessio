import unittest

from scheduling.workflows.parsing.schedules import OneOffRule, ScheduleItem, \
    canonicalize_item_times


def make_item(start_time: str | None, end_time: str | None) -> ScheduleItem:
    return ScheduleItem(
        church_id=1,
        date_rule=OneOffRule(month=1, day=1),
        start_time_iso8601=start_time,
        end_time_iso8601=end_time,
    )


class ScheduleItemTimeNormalizationTests(unittest.TestCase):
    """canonicalize_item_times is what get_schedule_items applies before the
    set-equality that drives the schedules_differs moderation."""

    def _assert_equivalent(self, item_a: ScheduleItem, item_b: ScheduleItem):
        canon_a = canonicalize_item_times(item_a)
        canon_b = canonicalize_item_times(item_b)
        self.assertEqual(canon_a, canon_b)
        self.assertEqual(hash(canon_a), hash(canon_b))
        # The exact operation behind check_schedules_match.
        self.assertEqual({canon_a}, {canon_b})

    def test_empty_end_time_equals_none(self):
        self._assert_equivalent(make_item('18:00:00', ''), make_item('18:00:00', None))

    def test_null_end_time_equals_none(self):
        self._assert_equivalent(make_item('18:00:00', 'null'), make_item('18:00:00', None))

    def test_empty_start_time_equals_none(self):
        self._assert_equivalent(make_item('', '18:00:00'), make_item(None, '18:00:00'))

    def test_canonical_value_is_none(self):
        self.assertIsNone(canonicalize_item_times(make_item('', 'null')).start_time_iso8601)
        self.assertIsNone(canonicalize_item_times(make_item('', 'null')).end_time_iso8601)

    def test_real_time_is_untouched(self):
        item = make_item('18:00:00', '18:30:00')
        canon = canonicalize_item_times(item)
        self.assertEqual(canon, item)
        self.assertEqual(canon.start_time_iso8601, '18:00:00')
        self.assertEqual(canon.end_time_iso8601, '18:30:00')

    def test_real_end_time_difference_still_differs(self):
        canon_a = canonicalize_item_times(make_item('18:00:00', '18:00:00'))
        canon_b = canonicalize_item_times(make_item('18:00:00', '18:30:00'))
        self.assertNotEqual(canon_a, canon_b)
        self.assertNotEqual({canon_a}, {canon_b})


if __name__ == '__main__':
    unittest.main()
