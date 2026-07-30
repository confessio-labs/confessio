from datetime import date

from scheduling.public_model import SourcedSchedulesList
from scheduling.workflows.parsing.holidays import HolidayZoneEnum
from scheduling.workflows.parsing.rrule_utils import has_upcoming_event


def remove_over_dated_items(sourced_schedules_list: SourcedSchedulesList,
                            holiday_zone: HolidayZoneEnum,
                            start_date: date | None = None,
                            default_year: int | None = None) -> SourcedSchedulesList | None:
    """Copy of the schedules without the items that have no occurrence left to come, or None when
    there is none to remove. Newly built schedules only ever keep items with an upcoming event, so
    an over-dated item can never match one of them."""
    sourced_schedules_of_churches = []
    has_removed_item = False
    for sourced_schedules_of_church in sourced_schedules_list.sourced_schedules_of_churches:
        upcoming_sourced_schedules = [
            sourced_schedule_item
            for sourced_schedule_item in sourced_schedules_of_church.sourced_schedules
            if has_upcoming_event(sourced_schedule_item.item, holiday_zone, start_date,
                                  default_year)
        ]
        if len(upcoming_sourced_schedules) != len(sourced_schedules_of_church.sourced_schedules):
            has_removed_item = True

        sourced_schedules_of_churches.append(sourced_schedules_of_church.model_copy(
            update={'sourced_schedules': upcoming_sourced_schedules}))

    if not has_removed_item:
        return None

    return sourced_schedules_list.model_copy(
        update={'sourced_schedules_of_churches': sourced_schedules_of_churches})
