from attaching.public_service import attaching_recognize_pdf
from core.utils.log_utils import info
from crawling.models import CrawlingModeration
from crawling.services.crawling_moderation_service import upsert_crawling_moderation, \
    get_crawling_moderation_category
from crawling.services.scrape_scraping_service import upsert_extracted_html_list, create_scraping
from crawling.services.scraping_service import delete_scraping
from crawling.services.widget_extraction_service import process_extracted_widgets
from crawling.utils.url_utils import get_path, get_domain, have_similar_domain
from crawling.workflows.crawl.download_and_search_urls import search_for_confession_pages, \
    get_new_url_and_aliases, forbid_diocese_home_links, CrawlingResult, is_new_url_valid
from crawling.workflows.scrape.download_refine_and_extract import get_extracted_html_list
from registry.models import Website, WebsiteModeration
from registry.public_service import registry_add_website_moderation, \
    registry_remove_not_validated_moderation


def update_home_url(website: Website, new_home_url: str):
    if not is_new_url_valid(new_home_url):
        print(f'This url is not eligible to home url update: {new_home_url}')
        return

    if len(new_home_url) > 200:
        registry_add_website_moderation(website, WebsiteModeration.Category.HOME_URL_TOO_LONG,
                                        other_home_url=new_home_url)
        return

    # Check that there is not already a Website with this home_url
    try:
        website_with_url = Website.objects.get(home_url=new_home_url)
        print(f'conflict between website {website.name} ({website.uuid}) '
              f'and {website_with_url.name} ({website_with_url.uuid}) '
              f'about url {new_home_url} Adding moderation.')
        registry_add_website_moderation(website, WebsiteModeration.Category.HOME_URL_CONFLICT,
                                        website_with_url)
    except Website.DoesNotExist:
        print(f'replacing home_url from {website.home_url} to {new_home_url} '
              f'for website {website.name}')
        website.home_url = new_home_url
        website.save()
        registry_remove_not_validated_moderation(website,
                                                 WebsiteModeration.Category.HOME_URL_CONFLICT)


def handle_diocese_domain(website: Website, domain_has_changed: bool,
                          aliases_domains: set[str],
                          forbidden_paths: set[str], path_redirection: dict[str, str]):
    diocese = website.get_diocese()
    if diocese and diocese.home_url:
        if domain_has_changed:
            info('check if diocese home_url has changed')
            new_diocese_url, diocese_aliases_domains, error_message = \
                get_new_url_and_aliases(diocese.home_url)
            if error_message:
                info(f'error in get_new_url_and_aliases for diocese with url {diocese.home_url}: '
                     f'{error_message}')
            elif new_diocese_url != diocese.home_url:
                if not is_new_url_valid(new_diocese_url):
                    print(f'This url is not eligible to diocese url update: {new_diocese_url}')
                else:
                    info(f'it has changed! Replacing it. New url: {new_diocese_url}')
                    diocese.home_url = new_diocese_url
                    diocese.save()

        if have_similar_domain(website.home_url, diocese.home_url):
            info('Website and diocese have similar domain, forbidding diocese home links')
            forbidden_paths |= forbid_diocese_home_links(diocese.home_url,
                                                         aliases_domains,
                                                         path_redirection)

        if website.home_url == diocese.home_url:
            registry_add_website_moderation(website, WebsiteModeration.Category.HOME_URL_DIOCESE)


def do_crawl_website(website: Website) -> CrawlingResult:
    if not website.enabled_for_crawling:
        return CrawlingResult()

    # Get home_url aliases
    new_home_url, aliases_domains, error_message = get_new_url_and_aliases(website.home_url)
    if error_message:
        return CrawlingResult(
            error_detail=f'error in get_url_aliases: {error_message}'
        )

    # Update home_url if needed
    if website.home_url != new_home_url:
        domain_has_changed = True
        update_home_url(website, new_home_url)
    else:
        domain_has_changed = False

    # Get any other website starting with the same home_url
    forbidden_outer_paths = set()
    for alias_domain in aliases_domains:
        same_domain_websites = Website.objects\
            .filter(home_url__contains=alias_domain, is_active=True)\
            .exclude(uuid=website.uuid).all()
        for other_website in same_domain_websites:
            if get_domain(other_website.home_url) in aliases_domains:
                forbidden_outer_paths.add(get_path(other_website.home_url))

    path_redirection = {}
    handle_diocese_domain(website,
                          domain_has_changed, aliases_domains, forbidden_outer_paths,
                          path_redirection)

    forbidden_paths = set()
    for forbidden_path in website.forbidden_paths.all():
        print(f'Adding forbidden path {forbidden_path.path} for website {website.name}')
        forbidden_paths.add(forbidden_path.path)

    # Actually crawling website
    return search_for_confession_pages(new_home_url, aliases_domains, forbidden_outer_paths,
                                       path_redirection, forbidden_paths)


def crawl_website(
        website: Website,
) -> tuple[CrawlingModeration.Category, CrawlingResult]:
    # check if website has parish
    if not website.parishes.exists() or not website.get_churches():
        website.delete()
        info('website has no parish or no churches, deleting it')
        return CrawlingModeration.Category.NO_RESPONSE, CrawlingResult()

    crawling_result = do_crawl_website(website)
    # use LLM vision to refine pdf extraction
    crawling_result = recognize_pdf_in_results(crawling_result)

    process_extracted_html(website, crawling_result)
    process_extracted_widgets(website, crawling_result.widgets)

    category = add_crawling_moderation(website, crawling_result)
    return category, crawling_result


def recognize_pdf_in_results(crawling_result: CrawlingResult) -> CrawlingResult:
    new_confession_pages = {}
    for url, (extracted_html_list, pdf_bytes) in crawling_result.confession_pages.items():
        if pdf_bytes is not None:
            pdf_html = attaching_recognize_pdf(url, pdf_bytes)
            new_extracted_html_list = get_extracted_html_list(pdf_html)
            if new_extracted_html_list:
                new_confession_pages[url] = (new_extracted_html_list, pdf_bytes)
        else:
            new_confession_pages[url] = (extracted_html_list, pdf_bytes)

    return crawling_result.model_copy(update={'confession_pages': new_confession_pages})


def process_extracted_html(
        website: Website,
        crawling_result: CrawlingResult,
):
    existing_scrapings = website.scrapings.all()
    existing_urls = list(map(lambda s: s.url, existing_scrapings))

    # New pages
    if crawling_result.confession_pages:
        for url, (extracted_html_list, _) in crawling_result.confession_pages.items():
            if url not in existing_urls:
                # Create new scraping
                create_scraping(extracted_html_list, url, website)

    # Existing scrapings
    for scraping in existing_scrapings:
        if scraping.url not in crawling_result.confession_pages:
            # Scraping did exist but not anymore, we remove it
            delete_scraping(scraping)
        else:
            # Scraping still exists, we update scraping
            upsert_extracted_html_list(scraping, crawling_result.confession_pages[scraping.url][0])


def add_crawling_moderation(website: Website,
                            crawling_result: CrawlingResult,
                            ) -> CrawlingModeration.Category:
    if not website.enabled_for_crawling:
        return CrawlingModeration.Category.NO_RESPONSE

    # Add moderation
    crawling_category, moderation_validated = get_crawling_moderation_category(website,
                                                                               crawling_result)
    upsert_crawling_moderation(website, crawling_category, moderation_validated)

    return crawling_category
