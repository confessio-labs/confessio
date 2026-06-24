from django.contrib.auth.models import User
from django.db.models.functions import Now

from registry.models import Website
from scheduling.models import ValidatedSchedules
from scheduling.public_model import SourcedSchedulesList, SourcedScheduleItem, ParsingSource
from scheduling.services.merging.sourced_schedules_service import retrieve_scheduling_elements
from scheduling.services.scheduling.scheduling_service import get_indexed_scheduling
from scheduling.workflows.merging.compare_explanations import ValidatedSchedulesComparison, \
    build_validated_schedules_comparison as build_comparison
from scheduling.workflows.parsing.schedules import ScheduleItem


#############################
# Create ValidatedSchedules #
#############################

def validate_website_indexed_schedules(website: Website, user: User):
    scheduling = get_indexed_scheduling(website)
    if scheduling is None:
        print(f'No indexed scheduling found for {website}')
        return

    try:
        validated_schedules = website.validated_schedules
        validated_schedules.validated_sourced_schedules_list = scheduling.sourced_schedules_list
        validated_schedules.validated_at = Now()
        validated_schedules.validated_by = user
    except ValidatedSchedules.DoesNotExist:
        validated_schedules = ValidatedSchedules(
            website=website,
            validated_sourced_schedules_list=scheduling.sourced_schedules_list,
            validated_at=Now(),
            validated_by=user
        )

    validated_schedules.save()


###############################
# Retrieve ValidatedSchedules #
###############################

def retrieve_validated_schedule(website: Website) -> SourcedSchedulesList | None:
    try:
        validated_schedules = website.validated_schedules
        return SourcedSchedulesList(**validated_schedules.validated_sourced_schedules_list)
    except ValidatedSchedules.DoesNotExist:
        return None


##############################
# Compare ValidatedSchedules #
##############################

def has_parsing_source(sourced_schedule_item: SourcedScheduleItem) -> bool:
    for source in sourced_schedule_item.sources:
        if isinstance(source, ParsingSource):
            return True

    return False


def get_schedule_items(sourced_schedules_list: SourcedSchedulesList) -> set[ScheduleItem]:
    schedule_items = set()
    for sourced_schedule_of_church in sourced_schedules_list.sourced_schedules_of_churches:
        for sourced_schedule_item in sourced_schedule_of_church.sourced_schedules:
            if not has_parsing_source(sourced_schedule_item):
                continue

            schedule_items.add(sourced_schedule_item.item)

    return schedule_items


def check_schedules_match(website: Website,
                          sourced_schedules_list: SourcedSchedulesList) -> bool | None:
    validated_sourced_schedules_list = retrieve_validated_schedule(website)
    if validated_sourced_schedules_list is None:
        return None

    return get_schedule_items(validated_sourced_schedules_list) == \
        get_schedule_items(sourced_schedules_list)


###############################################
# Compare ValidatedSchedules church by church #
###############################################

def build_website_validated_schedules_comparison(
        website: Website) -> ValidatedSchedulesComparison | None:
    scheduling = get_indexed_scheduling(website)
    if scheduling is None:
        return None

    scheduling_elements = retrieve_scheduling_elements(scheduling)

    validated_sourced_schedules_list = retrieve_validated_schedule(website)
    if validated_sourced_schedules_list is None:
        return None

    return build_comparison(
        validated_sourced_schedules_list,
        scheduling_elements.sourced_schedules_list,
        scheduling_elements.church_by_id,
    )
