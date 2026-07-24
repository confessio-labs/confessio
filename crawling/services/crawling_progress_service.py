from django.db import models

from core.services.background_task_service import get_locked_state_by_param

# Matches the @background task in crawling/tasks.py (module path + function name).
CRAWL_TASK_NAME = 'crawling.tasks.worker_crawl_website'


class CrawlingStatus(models.TextChoices):
    ENQUEUED = 'enqueued'
    IN_PROGRESS = 'in_progress'


def get_crawling_status_by_website_uuid(website_uuids: set[str]) -> dict[str, CrawlingStatus]:
    """Map each website UUID with a pending/running crawl task to its CrawlingStatus."""
    is_running_by_uuid = get_locked_state_by_param(CRAWL_TASK_NAME, website_uuids)
    return {
        website_uuid: CrawlingStatus.IN_PROGRESS if is_running else CrawlingStatus.ENQUEUED
        for website_uuid, is_running in is_running_by_uuid.items()
    }
