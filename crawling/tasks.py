import time

from background_task import background
from background_task.models import Task
from background_task.tasks import TaskSchedule

from core.utils.log_utils import info, start_log_buffer
from crawling.models import Log
from crawling.services.log_service import save_buffer
from registry.models import Website


@background(queue='crawling', schedule=TaskSchedule(priority=2))
def worker_crawl_website(website_uuid: str, timeout_ts: int | None):
    try:
        website = Website.objects.get(uuid=website_uuid)
    except Website.DoesNotExist:
        info(f'Website {website_uuid} does not exist for worker_crawl_website')
        return

    start_log_buffer()
    now = int(time.time())
    if timeout_ts and now > timeout_ts:
        info(f'Timeout reached before starting crawling, now = {now}, timeout_ts = {timeout_ts}')
        save_buffer(website, Log.Type.CRAWLING, Log.Status.TIMEOUT)
        return

    from crawling.services.website_worker_service import handle_crawl_website
    handle_crawl_website(website)


@background(queue='crawling', schedule=TaskSchedule(priority=1))
def worker_scrape_page(website_uuid: str, timeout_ts: int | None):
    try:
        website = Website.objects.get(uuid=website_uuid)
    except Website.DoesNotExist:
        info(f'Website {website_uuid} does not exist for worker_scrape_page')
        return

    start_log_buffer()
    now = int(time.time())
    if timeout_ts and now > timeout_ts:
        info(f'Timeout reached before starting scraping, now = {now}, timeout_ts = {timeout_ts}')
        save_buffer(website, Log.Type.SCRAPING, Log.Status.TIMEOUT)
        return

    from crawling.services.website_worker_service import handle_scrape_page
    handle_scrape_page(website)


def get_crawling_progress_by_website_uuid(website_uuids: set[str]) -> dict[str, str]:
    """For each website with a pending/running crawl task, return 'in_progress' or 'enqueued'."""
    from datetime import timedelta
    from django.db.models import Q
    from django.utils import timezone
    from core.settings import MAX_RUN_TIME

    if not website_uuids:
        return {}

    # Filter at the DB level so we only fetch rows for the websites actually on screen,
    # never the whole crawl queue (which can hold thousands of rows during a nightly crawl).
    # task_params is JSON text like [["<uuid>", null], {}] -> LIKE '%<uuid>%' per website.
    params_filter = Q()
    for website_uuid in website_uuids:
        params_filter |= Q(task_params__contains=website_uuid)

    fresh_lock_after = timezone.now() - timedelta(seconds=MAX_RUN_TIME)
    progress_by_uuid: dict[str, str] = {}
    tasks = Task.objects.filter(
        params_filter,
        task_name='crawling.tasks.worker_crawl_website',
    )
    for task in tasks:
        args, _ = task.params()
        if not args:
            continue
        website_uuid = args[0]
        if website_uuid not in website_uuids:  # safety net vs. LIKE false positives
            continue
        is_running = task.locked_by is not None and task.locked_at is not None \
            and task.locked_at > fresh_lock_after
        status = 'in_progress' if is_running else 'enqueued'
        # 'in_progress' wins if multiple rows exist for one website
        if progress_by_uuid.get(website_uuid) != 'in_progress':
            progress_by_uuid[website_uuid] = status
    return progress_by_uuid
