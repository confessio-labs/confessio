import json
from datetime import date

from django.template.defaulttags import register
from django.template.loader import render_to_string

from scheduling.models import Parsing
from scheduling.services.parsing.parsing_service import get_parsing_church_desc_by_id, \
    get_schedules_list_from_dict
from scheduling.services.scheduling.scheduling_service import get_prunings_of_parsing
from scheduling.utils.date_utils import get_current_year
from scheduling.workflows.parsing.compare_parsing_explanations import get_church_desc, \
    OTHER_CHURCH_DESC, build_schedules_list_diff
from scheduling.workflows.parsing.explain_schedule import get_explanation_from_schedule
from scheduling.workflows.parsing.holidays import HolidayZoneEnum
from scheduling.workflows.parsing.rrule_utils import get_events_from_schedule_item
from scheduling.workflows.parsing.schedules import ScheduleItem, Event, SchedulesList


@register.simple_tag
def explain_schedule(schedule: ScheduleItem, church_desc_by_id_json: str):
    church_desc_by_id = {int(k): v for (k, v) in json.loads(church_desc_by_id_json).items()}
    church_desc = get_church_desc(schedule.church_id, church_desc_by_id)
    explained_schedule = get_explanation_from_schedule(schedule)
    return render_to_string('displays/explained_schedule_display.html', {
        'explained_schedule': explained_schedule,
        'church_desc': church_desc,
    })


@register.filter
def get_schedule_item_events(schedule_item: ScheduleItem) -> list[Event]:
    start_date = date(2000, 1, 1)
    end_date = date(2040, 1, 1)
    default_year = get_current_year()
    default_holiday_zone = HolidayZoneEnum.FR_ZONE_A

    return get_events_from_schedule_item(schedule_item, default_holiday_zone,
                                         start_date, default_year,
                                         end_date)[:7]


###########
# DISPLAY #
###########

@register.simple_tag
def display_schedules_list(schedules_list: SchedulesList, church_desc_by_id_json: str):
    return render_to_string('displays/schedules_display.html', {
        'schedules_list': schedules_list,
        'schedules_list_json': schedules_list.model_dump_json(),
        'church_desc_by_id_json': church_desc_by_id_json,
    })


@register.simple_tag
def display_event(event: Event):
    return render_to_string('displays/event_display.html', {'event': event})


@register.simple_tag
def display_parsing_scrapings(parsing: Parsing):
    prunings = get_prunings_of_parsing(parsing)
    return render_to_string('displays/parsing_scrapings_display.html', {
        'prunings': prunings,
    })


@register.simple_tag
def display_parsing_content(parsing: Parsing):
    church_desc_by_id = get_parsing_church_desc_by_id(parsing)
    return render_to_string('displays/parsing_content_display.html', {
        'truncated_html': parsing.truncated_html,
        'churches': sorted(church_desc_by_id.items()),
        'other_church_desc': OTHER_CHURCH_DESC,
    })


def _get_schedules_list(some_json: dict | None, version: str) -> SchedulesList | None:
    return get_schedules_list_from_dict(some_json, version) if some_json else None


@register.simple_tag
def display_parsing_schedules_diff(parsing: Parsing):
    diff = build_schedules_list_diff(
        _get_schedules_list(parsing.llm_json, parsing.llm_json_version),
        _get_schedules_list(parsing.human_json, parsing.human_json_version),
        get_parsing_church_desc_by_id(parsing),
    )
    return render_to_string('displays/parsing_schedules_diff_display.html', {'diff': diff})
