import time

from background_task import background
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
