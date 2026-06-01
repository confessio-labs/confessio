from datetime import timedelta
from uuid import UUID

from front.public_service import front_get_church_color_by_uuid
from registry.models import Website
from scheduling.models import IndexEvent, Scheduling, Parsing
from scheduling.public_model import BaseSource, ParsingSource, OClocherSource
from scheduling.services.merging.holiday_zone_service import get_website_holiday_zone
from scheduling.services.merging.sourced_schedules_service import SchedulingElements
from scheduling.services.merging.timezone_service import get_timezone_of_church
from scheduling.utils.date_utils import datetime_in_timezone
from scheduling.workflows.parsing.intervals import periods_of_date
from scheduling.workflows.parsing.liturgical import PeriodEnum
from scheduling.workflows.parsing.rrule_utils import get_events_from_schedule_item
from scheduling.workflows.parsing.schedules import Event


def source_has_been_moderated(source: BaseSource,
                              parsing_by_uuid: dict[UUID, Parsing]) -> bool:
    if isinstance(source, ParsingSource):
        return parsing_by_uuid[source.parsing_uuid].has_been_moderated()

    if isinstance(source, OClocherSource):
        return True

    raise NotImplementedError


def generate_unique_events_by_church_id(website: Website, scheduling_elements: SchedulingElements,
                                        schedules_match_with_validated: bool | None
                                        ) -> dict[
    int | None,
    list[tuple[Event, list[int], bool, list[PeriodEnum]]]
]:
    parsing_by_uuid = {parsing.uuid: parsing for parsing in scheduling_elements.parsings}
    holiday_zone = get_website_holiday_zone(website,
                                            list(scheduling_elements.church_by_id.values()))

    events_by_church_id = {}
    for sourced_schedules_of_church in \
            scheduling_elements.sourced_schedules_list.sourced_schedules_of_churches:
        if not sourced_schedules_of_church.is_real_church():
            # We do not create events if not real church
            continue

        tuple_by_event = {}
        for i, sourced_schedule_item in enumerate(sourced_schedules_of_church.sourced_schedules):
            schedule_has_been_moderated = schedules_match_with_validated or \
                any(source_has_been_moderated(source, parsing_by_uuid)
                    for source in sourced_schedule_item.sources)
            events = get_events_from_schedule_item(sourced_schedule_item.item, holiday_zone,
                                                   max_days=10)
            for event in events:
                schedules_indices, has_been_moderated = tuple_by_event.get(event, ([], False))
                tuple_by_event[event] = (
                    schedules_indices + [i],
                    has_been_moderated or schedule_has_been_moderated,
                )

        unique_events = []
        for event, (schedules_indices, has_been_moderated) in tuple_by_event.items():
            unique_events.append((
                event,
                schedules_indices,
                has_been_moderated,
                periods_of_date(event.start.date(), holiday_zone)
            ))

        events_by_church_id[sourced_schedules_of_church.church_id] = unique_events

    return events_by_church_id


def build_index_events(scheduling: Scheduling,
                       scheduling_elements: SchedulingElements,
                       events_by_church_id: dict[
                           int | None,
                           list[tuple[Event, list[int], bool, list[PeriodEnum]]]
                       ]
                       ) -> list[IndexEvent]:
    church_color_by_uuid = front_get_church_color_by_uuid(
        scheduling_elements.sourced_schedules_list,
        scheduling_elements.church_by_id
    )

    index_events = []
    for church_id, event_and_moderations in events_by_church_id.items():
        church = scheduling_elements.church_by_id[church_id]
        church_color = church_color_by_uuid[church.uuid]
        church_tz = get_timezone_of_church(church)

        for event, schedules_indices, has_been_moderated, periods in event_and_moderations:
            midnight = event.start.replace(hour=23, minute=59, second=0, microsecond=0)
            if event.end is None:
                indexed_end_datetime = min(event.start + timedelta(hours=4), midnight)
            elif event.end < event.start:
                indexed_end_datetime = midnight
            else:
                indexed_end_datetime = event.end
            assert event.start <= indexed_end_datetime
            assert event.start.date() == indexed_end_datetime.date()

            event_day = event.start.date()
            start_time = event.start.time()
            displayed_end_time = event.end.time() if event.end else None
            indexed_end_time = indexed_end_datetime.time()
            start_tz_datetime = datetime_in_timezone(event.start, church_tz)
            indexed_end_tz_datetime = datetime_in_timezone(indexed_end_datetime, church_tz)

            index_events.append(IndexEvent(
                scheduling=scheduling,
                church=church,
                day=event_day,
                start_time=start_time,
                indexed_end_time=indexed_end_time,
                displayed_end_time=displayed_end_time,
                start_tz_datetime=start_tz_datetime,
                indexed_end_tz_datetime=indexed_end_tz_datetime,
                schedules_indices=schedules_indices,
                has_been_moderated=has_been_moderated,
                church_color=church_color,
                periods=periods,
            ))

    return index_events


def build_sourced_schedules_and_index_events(website: Website, scheduling: Scheduling,
                                             scheduling_elements: SchedulingElements,
                                             schedules_match_with_validated: bool | None
                                             ) -> list[IndexEvent]:
    # Generate events by church_id
    events_by_church_id = generate_unique_events_by_church_id(website, scheduling_elements,
                                                              schedules_match_with_validated)

    # Build index events
    index_event = build_index_events(scheduling, scheduling_elements, events_by_church_id)

    return index_event
