import unittest
from datetime import date
from uuid import uuid4

from scheduling.public_model import ParsingSource, SourcedSchedulesList, SourcedScheduleItem, \
    SourcedSchedulesOfChurch
from scheduling.utils.date_utils import Weekday
from scheduling.workflows.merging.filter_schedule_items import remove_over_dated_items
from scheduling.workflows.parsing.holidays import HolidayZoneEnum
from scheduling.workflows.parsing.schedules import OneOffRule, RegularRule, ScheduleItem, \
    WeeklyRule

TODAY = date(2026, 7, 30)
HOLIDAY_ZONE = HolidayZoneEnum.FR_ZONE_A
SourcedSchedulesByChurchId = dict[int | None, list[SourcedScheduleItem]]


def make_one_off_item(year: int | None, month: int, day: int,
                      weekday: Weekday | None = None) -> SourcedScheduleItem:
    return SourcedScheduleItem(
        item=ScheduleItem(
            church_id=3,
            date_rule=OneOffRule(year=year, month=month, day=day, weekday=weekday),
            start_time_iso8601='16:00:00',
            end_time_iso8601='18:00:00',
        ),
        explanation=f'le {day}/{month}/{year}',
        sources=[],
    )


def make_weekly_item(weekday: Weekday) -> SourcedScheduleItem:
    return SourcedScheduleItem(
        item=ScheduleItem(
            church_id=3,
            date_rule=RegularRule(rule=WeeklyRule(by_weekdays=[weekday])),
            start_time_iso8601='16:00:00',
            end_time_iso8601='18:00:00',
        ),
        explanation=f'tous les {weekday}',
        sources=[],
    )


def make_sourced_schedules_list(sourced_schedules_by_church_id: SourcedSchedulesByChurchId
                                ) -> SourcedSchedulesList:
    return SourcedSchedulesList(
        sourced_schedules_of_churches=[
            SourcedSchedulesOfChurch(church_id=church_id, sourced_schedules=sourced_schedules)
            for church_id, sourced_schedules in sourced_schedules_by_church_id.items()
        ],
        possible_by_appointment_sources=[],
        is_related_to_mass_sources=[],
        is_related_to_adoration_sources=[],
        is_related_to_permanence_sources=[],
        will_be_seasonal_events_sources=[],
    )


def remove_over_dated(sourced_schedules_list: SourcedSchedulesList) -> SourcedSchedulesList | None:
    return remove_over_dated_items(sourced_schedules_list, HOLIDAY_ZONE,
                                   start_date=TODAY, default_year=TODAY.year)


class RemoveOverDatedItemsTests(unittest.TestCase):
    """The validated snapshot is a frozen blob while newly built schedules only keep items with an
    upcoming event, so over-dated items must be dropped from it instead of counting as a change."""

    def test_returns_none_when_nothing_to_remove(self):
        sourced_schedules_list = make_sourced_schedules_list({
            3: [make_weekly_item(Weekday.WEDNESDAY), make_one_off_item(2026, 8, 15)],
        })

        self.assertIsNone(remove_over_dated(sourced_schedules_list))

    def test_removes_over_dated_item_and_keeps_the_others(self):
        kept = make_weekly_item(Weekday.WEDNESDAY)
        upcoming = make_one_off_item(2026, 8, 15)
        over_dated = make_one_off_item(2026, 7, 29)  # yesterday

        result = remove_over_dated(make_sourced_schedules_list({3: [kept, over_dated, upcoming]}))

        self.assertIsNotNone(result)
        self.assertEqual([kept, upcoming],
                         result.sourced_schedules_of_churches[0].sourced_schedules)

    def test_removes_year_less_over_dated_item(self):
        """The reported case: 29 July with no year, whose weekday resolves to a past year."""
        over_dated = make_one_off_item(None, 7, 29, weekday=Weekday.WEDNESDAY)

        result = remove_over_dated(make_sourced_schedules_list({3: [over_dated]}))

        self.assertIsNotNone(result)
        self.assertEqual([], result.sourced_schedules_of_churches[0].sourced_schedules)

    def test_keeps_churches_without_any_upcoming_item(self):
        result = remove_over_dated(make_sourced_schedules_list({
            3: [make_one_off_item(2026, 7, 29)],
            4: [make_weekly_item(Weekday.WEDNESDAY)],
            None: [],
        }))

        self.assertIsNotNone(result)
        self.assertEqual([3, 4, None],
                         [ssc.church_id for ssc in result.sourced_schedules_of_churches])
        self.assertEqual([], result.sourced_schedules_of_churches[0].sourced_schedules)

    def test_does_not_mutate_the_input(self):
        over_dated = make_one_off_item(2026, 7, 29)
        sourced_schedules_list = make_sourced_schedules_list({3: [over_dated]})

        remove_over_dated(sourced_schedules_list)

        self.assertEqual([over_dated],
                         sourced_schedules_list.sourced_schedules_of_churches[0].sourced_schedules)

    def test_preserves_flag_sources(self):
        source = ParsingSource(schedules_list=None, parsing_uuid=uuid4())
        sourced_schedules_list = make_sourced_schedules_list({3: [make_one_off_item(2026, 7, 29)]})
        sourced_schedules_list.is_related_to_mass_sources = [source]

        result = remove_over_dated(sourced_schedules_list)

        self.assertEqual([source], result.is_related_to_mass_sources)


if __name__ == '__main__':
    unittest.main()
