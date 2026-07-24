from core.services.background_task_service import TaskStatus, get_task_status_by_param

# Matches the @background task in crawling/tasks.py (module path + function name).
CRAWL_TASK_NAME = 'crawling.tasks.worker_crawl_website'


def get_crawling_status_by_website_uuid(website_uuids: set[str]) -> dict[str, TaskStatus]:
    """Map each website UUID with a pending/running crawl task to its TaskStatus."""
    return get_task_status_by_param(CRAWL_TASK_NAME, website_uuids)
