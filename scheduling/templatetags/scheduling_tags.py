import json
from datetime import date

from django.template.defaulttags import register
from django.template.loader import render_to_string

from scheduling.models import Parsing
from scheduling.services.scheduling.scheduling_service import get_prunings_of_parsing
from scheduling.utils.date_utils import get_current_year
from scheduling.workflows.parsing.compare_parsing_explanations import get_church_desc
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
