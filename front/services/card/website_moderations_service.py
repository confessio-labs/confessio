from uuid import UUID

from crawling.models import CrawlingModeration
from crawling.public_service import crawling_get_crawling_status_by_website_uuid, CrawlingStatus
from registry.models import Website
from scheduling.models import SchedulingModeration, ValidatedSchedulesModeration, Scheduling


def get_all_website_moderations(websites: list[Website]
                                ) -> tuple[
    dict[UUID, SchedulingModeration],
    dict[UUID, CrawlingModeration],
    dict[UUID, ValidatedSchedulesModeration],
    dict[UUID, Scheduling],
    dict[UUID, CrawlingStatus],
]:
    all_scheduling_moderations = SchedulingModeration.objects.filter(website__in=websites).all()
    scheduling_moderation_by_website = {}
    for scheduling_moderation in all_scheduling_moderations:
        scheduling_moderation_by_website[scheduling_moderation.website.uuid] = scheduling_moderation

    all_crawling_moderations = CrawlingModeration.objects.filter(website__in=websites).all()
    crawling_moderation_by_website = {}
    for crawling_moderation in all_crawling_moderations:
        crawling_moderation_by_website[crawling_moderation.website.uuid] = crawling_moderation

    all_validated_schedules_moderations = ValidatedSchedulesModeration.objects\
        .filter(website__in=websites).all()
    validated_schedules_moderation_by_website = {}
    for validated_schedules_moderation in all_validated_schedules_moderations:
        validated_schedules_moderation_by_website[validated_schedules_moderation.website.uuid] = \
            validated_schedules_moderation

    all_pending_schedulings = Scheduling.objects.filter(website__in=websites)\
        .exclude(status=Scheduling.Status.INDEXED).all()
    pending_scheduling_by_website = {}
    for pending_scheduling in all_pending_schedulings:
        pending_scheduling_by_website[pending_scheduling.website.uuid] = pending_scheduling

    crawling_status_by_uuid = crawling_get_crawling_status_by_website_uuid(
        {str(w.uuid) for w in websites})
    pending_crawling_by_website = {}
    for website in websites:
        crawling_status = crawling_status_by_uuid.get(str(website.uuid))
        if crawling_status:
            pending_crawling_by_website[website.uuid] = crawling_status

    return scheduling_moderation_by_website, crawling_moderation_by_website, \
        validated_schedules_moderation_by_website, pending_scheduling_by_website, \
        pending_crawling_by_website
