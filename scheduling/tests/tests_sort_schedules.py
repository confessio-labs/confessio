import unittest

from scheduling.utils.date_utils import Weekday
from scheduling.workflows.parsing.explain_schedule import schedule_item_sort_key
from scheduling.workflows.parsing.schedules import (DailyRule, MonthlyRule, NWeekday, OneOffRule,
                                                    Position, RegularRule, ScheduleItem,
                                                    WeeklyRule)


class SortSchedulesTests(unittest.TestCase):
    @staticmethod
    def get_fixtures():
        return [
            (
                OneOffRule(year=None, month=12, day=26, weekday=Weekday.FRIDAY),
                OneOffRule(year=2025, month=12, day=29, weekday=Weekday.MONDAY),
                OneOffRule(year=None, month=12, day=26, weekday=Weekday.FRIDAY),
            )
        ]

    def test_sort_schedules(self):
        for one_off_rule1, one_off_rule2, expected_first_one_off_rule in self.get_fixtures():
            with self.subTest():
                sorted_one_off_rules = sorted([one_off_rule2, one_off_rule1])
                first_one_off_rule = sorted_one_off_rules[0]
                # print(explanation)
                self.assertEqual(first_one_off_rule, expected_first_one_off_rule)


def weekly(weekdays: list[Weekday], start: str = '10:00:00') -> ScheduleItem:
    return ScheduleItem(date_rule=RegularRule(rule=WeeklyRule(by_weekdays=weekdays)),
                        start_time_iso8601=start)


class RegularRuleSortKeyTests(unittest.TestCase):
    def test_weekly_rules_sort_by_weekday(self):
        """The weekdays live on RegularRule.rule; reading them off the wrapper used to give every
        weekly rule the same key, so they fell back to sorting by start time."""
        schedules = [weekly([Weekday.SATURDAY], '08:00:00'), weekly([Weekday.MONDAY], '19:00:00'),
                     weekly([Weekday.FRIDAY], '15:00:00')]

        sorted_schedules = sorted(schedules, key=schedule_item_sort_key)

        self.assertEqual([s.date_rule.rule.by_weekdays[0] for s in sorted_schedules],
                         [Weekday.MONDAY, Weekday.FRIDAY, Weekday.SATURDAY])

    def test_fewer_weekdays_come_first(self):
        one_day = weekly([Weekday.SUNDAY])
        two_days = weekly([Weekday.MONDAY, Weekday.TUESDAY])

        self.assertEqual(sorted([two_days, one_day], key=schedule_item_sort_key),
                         [one_day, two_days])

    def test_frequency_order_is_daily_weekly_monthly(self):
        daily = ScheduleItem(date_rule=RegularRule(rule=DailyRule()), start_time_iso8601='10:00:00')
        monthly = ScheduleItem(
            date_rule=RegularRule(rule=MonthlyRule(
                by_nweekdays=[NWeekday(weekday=Weekday.SUNDAY, position=Position.FIRST)])),
            start_time_iso8601='10:00:00')

        self.assertEqual(sorted([monthly, weekly([Weekday.MONDAY]), daily],
                                key=schedule_item_sort_key),
                         [daily, weekly([Weekday.MONDAY]), monthly])


if __name__ == '__main__':
    unittest.main()
