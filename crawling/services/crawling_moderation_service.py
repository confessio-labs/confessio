from crawling.models import CrawlingModeration
from crawling.workflows.crawl.download_and_search_urls import CrawlingResult
from registry.models import Website
from registry.models.base_moderation_models import ModerationStatus


def upsert_crawling_moderation(website: Website, category: CrawlingModeration.Category,
                               moderation_validated: bool) -> CrawlingModeration:
    status = (ModerationStatus.VALIDATED
              if moderation_validated
              else ModerationStatus.TO_VALIDATE)
    # get_or_create so that two concurrent crawls of the same website don't both insert
    moderation, created = CrawlingModeration.objects.get_or_create(
        website=website,
        defaults={
            'category': category,
            'diocese': website.get_diocese(),
            'status': status,
        },
    )
    if not created and moderation.category != category:
        moderation.category = category
        moderation.status = status
        moderation.save()

    return moderation


def get_crawling_moderation_category(website: Website,
                                     crawling_result: CrawlingResult
                                     ) -> tuple[CrawlingModeration.Category, bool]:
    if crawling_result.confession_pages and website.scrapings.exists():
        return CrawlingModeration.Category.OK, True
    elif crawling_result.visited_links_count > 0:
        return CrawlingModeration.Category.NO_PAGE, False
    else:
        return CrawlingModeration.Category.NO_RESPONSE, False
