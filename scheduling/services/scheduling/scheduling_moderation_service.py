from crawling.models import CrawlingModeration
from registry.models.base_moderation_models import ModerationStatus
from scheduling.models import Scheduling, IndexEvent
from scheduling.models.scheduling_moderation_models import SchedulingModeration
from scheduling.public_model import SourcedSchedulesList
from scheduling.services.merging.schedules_conflict_service import website_has_schedules_conflict
from scheduling.services.parsing.church_desc_service import churches_have_desc_conflict
from scheduling.services.scheduling.scheduling_service import get_scheduling_sources


def has_crawling_moderation_been_validated(scheduling: Scheduling) -> bool:
    return CrawlingModeration.objects.filter(
        website=scheduling.website,
        category__in=[CrawlingModeration.Category.NO_RESPONSE, CrawlingModeration.Category.NO_PAGE],
        status=ModerationStatus.VALIDATED,
    ).exists()


def get_scheduling_moderation_category(scheduling: Scheduling,
                                       index_events: list[IndexEvent],
                                       sourced_schedules_list: SourcedSchedulesList
                                       ) -> tuple[SchedulingModeration.Category, bool]:
    scheduling_sources = get_scheduling_sources(scheduling)
    if not scheduling_sources.parsings and not scheduling_sources.oclocher_schedules:
        moderation_validated = has_crawling_moderation_been_validated(scheduling)
        return SchedulingModeration.Category.NO_SOURCE, moderation_validated

    if not index_events:
        return SchedulingModeration.Category.NO_SCHEDULE, False

    if churches_have_desc_conflict(scheduling_sources.churches):
        return SchedulingModeration.Category.DESC_CONFLICT, False

    if not all(map(lambda s: s.is_real_church(),
                   sourced_schedules_list.sourced_schedules_of_churches)):
        return SchedulingModeration.Category.UNKNOWN_PLACE, False

    if website_has_schedules_conflict(index_events):
        return SchedulingModeration.Category.SCHEDULES_CONFLICT, False

    return SchedulingModeration.Category.OK, True
