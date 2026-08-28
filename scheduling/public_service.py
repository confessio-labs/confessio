from registry.models import Website
from scheduling.models import Parsing, Scheduling
from scheduling.models.pruning_models import Sentence, Pruning
from scheduling.public_model import SchedulesList
from scheduling.services.merging.sourced_schedules_service import SchedulingElements, \
    retrieve_scheduling_elements
from scheduling.services.parsing.parsing_service import has_schedules, get_dict_and_version, \
    get_parsing_church_desc_by_id, get_parsing_schedules_list, get_schedules_list_from_dict
from scheduling.services.pruning.prune_scraping_service import create_pruning, \
    remove_pruning_moderation_if_orphan
from scheduling.services.scheduling.scheduling_process_service import init_scheduling
from scheduling.services.scheduling.scheduling_service import get_websites_of_prunings, \
    get_websites_of_parsing, get_indexed_scheduling, SchedulingSources, get_scheduling_sources, \
    SchedulingPrimarySources, get_scheduling_primary_sources
from scheduling.workflows.parsing.schedules import SCHEDULES_LIST_VERSION


###########
# PRUNING #
###########

def scheduling_create_pruning(extracted_html: str | None) -> Pruning | None:
    return create_pruning(extracted_html)


def scheduling_remove_pruning_moderation_if_orphan(pruning: Pruning):
    remove_pruning_moderation_if_orphan(pruning)


###########
# PARSING #
###########

def scheduling_has_schedules(parsing: Parsing) -> bool:
    return has_schedules(parsing)


def scheduling_get_parsing_church_desc_by_id(parsing: Parsing) -> dict[int, str]:
    return get_parsing_church_desc_by_id(parsing)


def scheduling_get_parsing_dict_and_version(parsing: Parsing) -> tuple[dict, str]:
    return get_dict_and_version(parsing)


def scheduling_get_parsing_schedules_list(parsing: Parsing) -> SchedulesList | None:
    return get_parsing_schedules_list(parsing)


def scheduling_get_schedules_list_from_dict(schedules_list_as_dict: dict,
                                            version: str) -> SchedulesList | None:
    return get_schedules_list_from_dict(schedules_list_as_dict, version)


def scheduling_update_parsing_human_json(parsing: Parsing, schedules_list: SchedulesList):
    """Write a schedules list as the human-validated json of a parsing, at the current version.

    Imported lazily: edit_parsing_service needs init_schedulings_for_parsing from this very
    module, so a module-level import would be circular.
    """
    from scheduling.services.parsing.edit_parsing_service import set_human_json

    set_human_json(parsing, schedules_list.model_dump(mode='json'), SCHEDULES_LIST_VERSION)


###################
# INIT SCHEDULING #
###################

def scheduling_init_scheduling(website: Website, instant_deindex: bool = False) -> Scheduling:
    return init_scheduling(website, instant_deindex)


def init_scheduling_for_sentences(sentences: list[Sentence]):
    affected_prunings = []
    for sentence in sentences:
        for pruning in sentence.prunings.all():
            if pruning not in affected_prunings:
                affected_prunings.append(pruning)

    for website in get_websites_of_prunings(affected_prunings):
        init_scheduling(website)


def init_scheduling_for_pruning(pruning: Pruning):
    websites = get_websites_of_prunings([pruning])
    for website in websites:
        init_scheduling(website)


def init_schedulings_for_parsing(parsing: Parsing):
    websites = get_websites_of_parsing(parsing)
    for website in websites:
        init_scheduling(website)


##################
# GET SCHEDULING #
##################

def scheduling_get_indexed_scheduling(website: Website) -> Scheduling | None:
    return get_indexed_scheduling(website)


###################
# RELATED OBJECTS #
###################

def scheduling_retrieve_scheduling_elements(scheduling: Scheduling) -> SchedulingElements:
    return retrieve_scheduling_elements(scheduling)


def scheduling_get_scheduling_sources(scheduling: Scheduling | None) -> SchedulingSources:
    return get_scheduling_sources(scheduling)


def scheduling_get_scheduling_primary_sources(scheduling: Scheduling | None
                                              ) -> SchedulingPrimarySources:
    return get_scheduling_primary_sources(scheduling)
