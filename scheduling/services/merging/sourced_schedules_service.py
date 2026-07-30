from dataclasses import dataclass

from scheduling.services.merging.holiday_zone_service import get_website_holiday_zone
from registry.models import Church, Website
from scheduling.models import Parsing
from scheduling.models import Scheduling
from scheduling.public_model import SourcedSchedulesList, SourcedScheduleItem, \
    SourcedSchedulesOfChurch, BaseSource
from scheduling.services.merging.sources_service import get_church_by_id_and_sources
from scheduling.services.scheduling.scheduling_service import get_scheduling_sources
from scheduling.workflows.merging.merge_schedule_items import get_merged_sourced_schedule_items
from scheduling.workflows.merging.sort_schedule_items import \
    get_sorted_sourced_schedule_items_by_church_id
from scheduling.workflows.parsing.explain_schedule import get_explanation_from_schedule
from scheduling.workflows.parsing.rrule_utils import has_upcoming_event

MAX_SCHEDULES_PER_CHURCH = 30


def get_sourced_schedules_list(website: Website,
                               church_by_id: dict[int, Church],
                               sources: list[BaseSource],
                               ) -> SourcedSchedulesList:
    ###########################
    # Get SourcedScheduleItem #
    ###########################

    all_sourced_schedule_items = []

    holiday_zone = get_website_holiday_zone(website, list(church_by_id.values()))

    possible_by_appointment_sources = []
    is_related_to_mass_sources = []
    is_related_to_adoration_sources = []
    is_related_to_permanence_sources = []
    will_be_seasonal_events_sources = []

    for source in sources:
        schedules_list = source.schedules_list
        if schedules_list is None:
            continue

        for schedule_item in schedules_list.schedules:
            if has_upcoming_event(schedule_item, holiday_zone):
                all_sourced_schedule_items.append(
                    SourcedScheduleItem(
                        item=schedule_item,
                        explanation=get_explanation_from_schedule(schedule_item),
                        sources=[source],
                    )
                )

        if schedules_list.possible_by_appointment:
            possible_by_appointment_sources.append(source)
        if schedules_list.is_related_to_mass:
            is_related_to_mass_sources.append(source)
        if schedules_list.is_related_to_adoration:
            is_related_to_adoration_sources.append(source)
        if schedules_list.is_related_to_permanence:
            is_related_to_permanence_sources.append(source)
        if schedules_list.will_be_seasonal_events:
            will_be_seasonal_events_sources.append(source)

    merged_sourced_schedule_items = get_merged_sourced_schedule_items(all_sourced_schedule_items)
    sorted_sourced_schedule_items_by_church_id = get_sorted_sourced_schedule_items_by_church_id(
        merged_sourced_schedule_items
    )

    #####################################
    # Get sourced_schedules_of_churches #
    #####################################

    sourced_schedules_of_churches = [
        SourcedSchedulesOfChurch(
            church_id=church_id,
            sourced_schedules=sourced_schedule_items[:MAX_SCHEDULES_PER_CHURCH],
        )
        for church_id, sourced_schedule_items in sorted_sourced_schedule_items_by_church_id.items()
    ]

    # Add churches without events
    church_ids_with_events = {ssc.church_id for ssc in sourced_schedules_of_churches}
    sourced_schedules_of_churches += [
        SourcedSchedulesOfChurch(
            church_id=church_id,
            sourced_schedules=[]
        ) for church_id in church_by_id if church_id not in church_ids_with_events
    ]

    return SourcedSchedulesList(
        sourced_schedules_of_churches=sourced_schedules_of_churches,
        possible_by_appointment_sources=possible_by_appointment_sources,
        is_related_to_mass_sources=is_related_to_mass_sources,
        is_related_to_adoration_sources=is_related_to_adoration_sources,
        is_related_to_permanence_sources=is_related_to_permanence_sources,
        will_be_seasonal_events_sources=will_be_seasonal_events_sources,
    )


@dataclass
class SchedulingElements:
    sourced_schedules_list: SourcedSchedulesList
    church_by_id: dict[int, Church]
    parsings: list[Parsing]


def build_scheduling_elements(website: Website, scheduling: Scheduling | None
                              ) -> SchedulingElements:
    assert scheduling.status == Scheduling.Status.MATCHED

    scheduling_sources = get_scheduling_sources(scheduling)
    church_by_id, sources = get_church_by_id_and_sources(scheduling_sources)
    sourced_schedules_list = get_sourced_schedules_list(website, church_by_id, sources)

    return SchedulingElements(
        sourced_schedules_list=sourced_schedules_list,
        church_by_id=church_by_id,
        parsings=scheduling_sources.parsings
    )


def retrieve_scheduling_elements(scheduling: Scheduling) -> SchedulingElements:
    assert scheduling.status == Scheduling.Status.INDEXED
    assert scheduling.sourced_schedules_list is not None
    assert scheduling.church_uuid_by_id is not None

    sourced_schedules_list = SourcedSchedulesList(**scheduling.sourced_schedules_list)
    scheduling_sources = get_scheduling_sources(scheduling)
    church_by_uuid = {str(church.uuid): church for church in scheduling_sources.churches}
    church_by_id = {int(church_id): church_by_uuid[church_uuid]
                    for church_id, church_uuid in scheduling.church_uuid_by_id.items()}

    return SchedulingElements(
        sourced_schedules_list=sourced_schedules_list,
        church_by_id=church_by_id,
        parsings=scheduling_sources.parsings,
    )
