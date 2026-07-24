from dataclasses import dataclass

from scheduling.models import Parsing, SchedulingModeration
from scheduling.models import Scheduling, IndexEvent
from scheduling.public_model import SourcedSchedulesList
from scheduling.services.merging.index_events_service import \
    build_sourced_schedules_and_index_events
from scheduling.services.merging.validated_schedules_service import check_schedules_match
from scheduling.services.merging.sourced_schedules_service import build_scheduling_elements
from scheduling.services.parsing.parse_pruning_service import remove_useless_moderation_for_parsing
from scheduling.services.scheduling.scheduling_moderation_service import \
    get_scheduling_moderation_category
from scheduling.services.scheduling.scheduling_service import build_resources_hash


@dataclass
class SchedulingIndexingObjects:
    sourced_schedules_list: SourcedSchedulesList
    church_uuid_by_id: dict[int, str]
    index_events: list[IndexEvent]
    resources_hash: str
    schedules_match_with_validated: bool | None
    moderation_category: SchedulingModeration.Category
    moderation_validated: bool


def do_index_scheduling(scheduling: Scheduling) -> SchedulingIndexingObjects:
    # Build scheduling elements
    scheduling_elements = build_scheduling_elements(scheduling.website, scheduling)

    church_uuid_by_id = {church_id: str(church.uuid) for church_id, church
                         in scheduling_elements.church_by_id.items()}

    # We check if schedules differs from validated schedules for website
    schedules_match_with_validated = check_schedules_match(
        scheduling.website, scheduling_elements.sourced_schedules_list)

    # Build index events
    index_events = build_sourced_schedules_and_index_events(scheduling.website, scheduling,
                                                            scheduling_elements,
                                                            schedules_match_with_validated)

    # Prepare moderation
    moderation_category, moderation_validated = get_scheduling_moderation_category(
        scheduling, index_events, scheduling_elements.sourced_schedules_list)

    # We build the resources hash to avoid doing it inside the transaction
    resources_hash = build_resources_hash(scheduling, scheduling_elements.sourced_schedules_list,
                                          church_uuid_by_id, index_events,
                                          schedules_match_with_validated,
                                          moderation_category, moderation_validated)

    return SchedulingIndexingObjects(
        sourced_schedules_list=scheduling_elements.sourced_schedules_list,
        church_uuid_by_id=church_uuid_by_id,
        index_events=index_events,
        resources_hash=resources_hash,
        schedules_match_with_validated=schedules_match_with_validated,
        moderation_category=moderation_category,
        moderation_validated=moderation_validated,
    )


def clean_parsings_moderations(parsing_history_ids: list[int]):
    for parsing_history_id in parsing_history_ids:
        historical_parsing = Parsing.history.get(history_id=parsing_history_id)
        parsing = historical_parsing.instance
        remove_useless_moderation_for_parsing(parsing)
