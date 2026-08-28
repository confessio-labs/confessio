import unittest

from scheduling.utils.date_utils import Weekday
from scheduling.workflows.parsing.compare_parsing_explanations import (
    OTHER_CHURCH_DESC, UNKNOWN_CHURCH_DESC, build_schedules_list_diff, explain_schedules,
    get_church_desc, safe_explanation)
from scheduling.workflows.parsing.liturgical import PeriodEnum
from scheduling.workflows.parsing.schedules import (OneOffRule, RegularRule, ScheduleItem,
                                                    SchedulesList, WeeklyRule)

CHURCH_DESC_BY_ID = {0: 'Église Saint-Pierre', 1: 'Église Sainte-Anne'}


def make_schedule(weekday: Weekday, start: str, church_id: int | None = 0,
                  only_in_periods: list | None = None) -> ScheduleItem:
    return ScheduleItem(
        church_id=church_id,
        date_rule=RegularRule(rule=WeeklyRule(by_weekdays=[weekday]),
                              only_in_periods=only_in_periods or []),
        start_time_iso8601=start,
    )


def make_schedules_list(schedules: list[ScheduleItem], **flags) -> SchedulesList:
    return SchedulesList(schedules=schedules, **flags)


class GetChurchDescTests(unittest.TestCase):
    def test_known_id(self):
        self.assertEqual(get_church_desc(1, CHURCH_DESC_BY_ID), 'Église Sainte-Anne')

    def test_other_church(self):
        self.assertEqual(get_church_desc(-1, CHURCH_DESC_BY_ID), OTHER_CHURCH_DESC)

    def test_none_and_unknown_id(self):
        self.assertEqual(get_church_desc(None, CHURCH_DESC_BY_ID), UNKNOWN_CHURCH_DESC)
        self.assertEqual(get_church_desc(42, CHURCH_DESC_BY_ID), UNKNOWN_CHURCH_DESC)


class SafeExplanationTests(unittest.TestCase):
    def test_explainable(self):
        explanation = safe_explanation(make_schedule(Weekday.SATURDAY, '10:00:00'))
        self.assertEqual(explanation, 'Toutes les semaines le samedi à partir de 10:00.')

    def test_unexplainable_does_not_raise(self):
        # HOLY_WEEK has no entry in get_name_by_period, so explaining it raises.
        schedule = make_schedule(Weekday.SATURDAY, '10:00:00',
                                 only_in_periods=[PeriodEnum.HOLY_WEEK])
        explanation = safe_explanation(schedule)
        self.assertTrue(explanation.startswith('⚠️ Horaire inexplicable'))


def make_one_off(month: int, day: int, church_id: int = 0) -> ScheduleItem:
    return ScheduleItem(church_id=church_id,
                        date_rule=OneOffRule(year=2026, month=month, day=day),
                        start_time_iso8601='10:00:00')


class ExplainSchedulesOrderTests(unittest.TestCase):
    def test_one_off_dates_read_chronologically(self):
        """Not alphabetically: 'le jeudi 9 juillet' must not sort before 'le mercredi 1 juillet'."""
        schedules_list = make_schedules_list([make_one_off(7, 9), make_one_off(7, 1),
                                              make_one_off(6, 30)])
        lines = explain_schedules(schedules_list, CHURCH_DESC_BY_ID)

        self.assertEqual([line.split(' : ')[1] for line in lines], [
            'Le mardi 30 juin 2026 à partir de 10:00.',
            'Le mercredi 01 juillet 2026 à partir de 10:00.',
            'Le jeudi 09 juillet 2026 à partir de 10:00.',
        ])

    def test_regular_rules_come_before_one_off_dates(self):
        schedules_list = make_schedules_list([make_one_off(7, 1),
                                              make_schedule(Weekday.SATURDAY, '10:00:00')])
        lines = explain_schedules(schedules_list, CHURCH_DESC_BY_ID)

        self.assertTrue(lines[0].endswith('Toutes les semaines le samedi à partir de 10:00.'))
        self.assertTrue(lines[1].endswith('Le mercredi 01 juillet 2026 à partir de 10:00.'))

    def test_unsortable_schedule_goes_last_without_raising(self):
        unsortable = make_schedule(Weekday.SATURDAY, '10:00:00',
                                   only_in_periods=[PeriodEnum.HOLY_WEEK])
        schedules_list = make_schedules_list([unsortable, make_one_off(7, 1)])
        lines = explain_schedules(schedules_list, CHURCH_DESC_BY_ID)

        self.assertIn('⚠️', lines[-1])

    def test_church_desc_prefixes_each_line(self):
        schedules_list = make_schedules_list([make_one_off(7, 1, church_id=1)])
        self.assertEqual(explain_schedules(schedules_list, CHURCH_DESC_BY_ID),
                         ['Église Sainte-Anne : Le mercredi 01 juillet 2026 à partir de 10:00.'])


class SchedulesListDiffTests(unittest.TestCase):
    def test_unchanged_schedule_is_not_flagged(self):
        schedules_list = make_schedules_list([make_schedule(Weekday.SATURDAY, '10:00:00')])
        diff = build_schedules_list_diff(schedules_list, schedules_list, CHURCH_DESC_BY_ID)

        self.assertEqual(len(diff.church_diffs), 1)
        church_diff = diff.church_diffs[0]
        self.assertEqual(church_diff.church_desc, 'Église Saint-Pierre')
        self.assertFalse(church_diff.differs)
        self.assertFalse(any(line.changed for line in church_diff.before_lines))
        self.assertFalse(any(line.changed for line in church_diff.after_lines))
        self.assertFalse(diff.any_differs)

    def test_removed_and_added_lines(self):
        before = make_schedules_list([make_schedule(Weekday.SATURDAY, '10:00:00'),
                                      make_schedule(Weekday.MONDAY, '09:00:00')])
        after = make_schedules_list([make_schedule(Weekday.SATURDAY, '10:00:00'),
                                     make_schedule(Weekday.FRIDAY, '18:00:00')])
        diff = build_schedules_list_diff(before, after, CHURCH_DESC_BY_ID)

        church_diff = diff.church_diffs[0]
        self.assertTrue(church_diff.differs)
        self.assertTrue(diff.any_differs)
        removed = [line.text for line in church_diff.before_lines if line.changed]
        added = [line.text for line in church_diff.after_lines if line.changed]
        self.assertEqual(len(removed), 1)
        self.assertIn('lundi', removed[0])
        self.assertEqual(len(added), 1)
        self.assertIn('vendredi', added[0])

    def test_church_present_on_one_side_only(self):
        before = make_schedules_list([make_schedule(Weekday.SATURDAY, '10:00:00', church_id=0)])
        after = make_schedules_list([make_schedule(Weekday.SATURDAY, '10:00:00', church_id=0),
                                     make_schedule(Weekday.SUNDAY, '11:00:00', church_id=1)])
        diff = build_schedules_list_diff(before, after, CHURCH_DESC_BY_ID)

        by_desc = {c.church_desc: c for c in diff.church_diffs}
        self.assertEqual(set(by_desc), {'Église Saint-Pierre', 'Église Sainte-Anne'})
        self.assertFalse(by_desc['Église Saint-Pierre'].differs)
        sainte_anne = by_desc['Église Sainte-Anne']
        self.assertTrue(sainte_anne.differs)
        self.assertEqual(sainte_anne.before_lines, [])
        self.assertTrue(all(line.changed for line in sainte_anne.after_lines))
        # Differing churches come first.
        self.assertEqual(diff.church_diffs[0].church_desc, 'Église Sainte-Anne')

    def test_no_before_json(self):
        after = make_schedules_list([make_schedule(Weekday.SATURDAY, '10:00:00')],
                                    possible_by_appointment=True)
        diff = build_schedules_list_diff(None, after, CHURCH_DESC_BY_ID)

        church_diff = diff.church_diffs[0]
        self.assertEqual(church_diff.before_lines, [])
        self.assertTrue(all(line.changed for line in church_diff.after_lines))
        self.assertTrue(diff.any_differs)

    def test_flags(self):
        before = make_schedules_list([], possible_by_appointment=True)
        after = make_schedules_list([], possible_by_appointment=True, is_related_to_mass=True)
        diff = build_schedules_list_diff(before, after, CHURCH_DESC_BY_ID)

        by_label = {flag.label: flag for flag in diff.flag_diffs}
        self.assertEqual(len(diff.flag_diffs), 5)
        self.assertFalse(by_label['Sur rendez-vous'].differs)
        self.assertTrue(by_label['Sur rendez-vous'].before_on)
        self.assertTrue(by_label['Lié à la messe'].differs)
        self.assertFalse(by_label['Lié à la messe'].before_on)
        self.assertTrue(by_label['Lié à la messe'].after_on)
        self.assertFalse(by_label['Lié à une permanence'].differs)
        self.assertTrue(diff.any_differs)

    def test_unexplainable_schedule_is_rendered_not_raised(self):
        after = make_schedules_list([make_schedule(Weekday.SATURDAY, '10:00:00',
                                                   only_in_periods=[PeriodEnum.HOLY_WEEK])])
        diff = build_schedules_list_diff(None, after, CHURCH_DESC_BY_ID)

        self.assertTrue(diff.church_diffs[0].after_lines[0].text.startswith('⚠️'))


if __name__ == '__main__':
    unittest.main()
