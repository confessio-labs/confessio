from dataclasses import dataclass
from uuid import UUID

from django.db.models import prefetch_related_objects

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


def retrieve_schedulings_elements(schedulings: list[Scheduling]
                                  ) -> dict[UUID, SchedulingElements]:
    # Load everything up front: a scheduling can be deleted (with its related objects) by a
    # concurrent indexing while we are still serializing the others.
    prefetch_related_objects(schedulings, 'historical_churches', 'pruning_parsings')

    church_history_ids = {historical_church.church_history_id
                          for scheduling in schedulings
                          for historical_church in scheduling.historical_churches.all()}
    # Not using .instance: it queries the live Church per item to fill the excluded name_norm
    church_by_history_id = {
        historical_church.history_id: Church(**{
            field.attname: getattr(historical_church, field.attname)
            for field in historical_church.tracked_fields
        })
        for historical_church in Church.history.filter(history_id__in=church_history_ids)
    }

    parsing_history_ids = {pruning_parsing.parsing_history_id
                           for scheduling in schedulings
                           for pruning_parsing in scheduling.pruning_parsings.all()}
    parsing_by_history_id = {
        historical_parsing.history_id: historical_parsing.instance
        for historical_parsing in Parsing.history.filter(history_id__in=parsing_history_ids)
    }

    scheduling_elements_by_uuid = {}
    for scheduling in schedulings:
        assert scheduling.status == Scheduling.Status.INDEXED
        assert scheduling.sourced_schedules_list is not None
        assert scheduling.church_uuid_by_id is not None

        sourced_schedules_list = SourcedSchedulesList(**scheduling.sourced_schedules_list)
        church_by_uuid = {
            str(church_by_history_id[historical_church.church_history_id].uuid):
                church_by_history_id[historical_church.church_history_id]
            for historical_church in scheduling.historical_churches.all()
        }
        church_by_id = {int(church_id): church_by_uuid[church_uuid]
                        for church_id, church_uuid in scheduling.church_uuid_by_id.items()}

        parsings = []
        for pruning_parsing in scheduling.pruning_parsings.all():
            parsing = parsing_by_history_id[pruning_parsing.parsing_history_id]
            if parsing not in parsings:
                parsings.append(parsing)

        scheduling_elements_by_uuid[scheduling.uuid] = SchedulingElements(
            sourced_schedules_list=sourced_schedules_list,
            church_by_id=church_by_id,
            parsings=parsings,
        )

    return scheduling_elements_by_uuid


def retrieve_scheduling_elements(scheduling: Scheduling) -> SchedulingElements:
    return retrieve_schedulings_elements([scheduling])[scheduling.uuid]
