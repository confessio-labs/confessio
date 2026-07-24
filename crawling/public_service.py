from crawling.services.crawling_progress_service import CrawlingStatus, \
    get_crawling_status_by_website_uuid
from crawling.tasks import worker_crawl_website
from registry.models import Website

__all__ = ['CrawlingStatus']


def crawling_crawl_website(website: Website):
    worker_crawl_website(str(website.uuid), None)


def crawling_get_crawling_status_by_website_uuid(website_uuids: set[str]
                                                 ) -> dict[str, CrawlingStatus]:
    return get_crawling_status_by_website_uuid(website_uuids)


def crawling_get_content_from_url(url: str) -> tuple[str, bytes | None] | None:
    """Fetch a page's text (and optional PDF bytes). Returns None on timeout / 4xx / 5xx."""
    from crawling.workflows.download.download_content import get_content_from_url
    return get_content_from_url(url)
