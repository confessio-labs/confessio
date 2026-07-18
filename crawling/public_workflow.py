from crawling.workflows.crawl.download_and_search_urls import get_new_url_and_aliases, \
    is_new_url_valid
from crawling.workflows.download.download_content import redirects_to_other_url, \
    get_content_from_url
from crawling.workflows.scrape.download_refine_and_extract import get_extracted_html_list, \
    get_extracted_v2_html_list


######################
# REFINE AND EXTRACT #
######################

def crawling_get_extracted_html_list(html_content: str) -> list[str] | None:
    return get_extracted_html_list(html_content)


def crawling_get_extracted_v2_html_list(html_content: str) -> list[str] | None:
    return get_extracted_v2_html_list(html_content)


###################
# URL REDIRECTION #
###################

def crawling_get_new_url_and_aliases(url: str) -> tuple[str, set[str], str | None]:
    return get_new_url_and_aliases(url)


def crawling_is_new_url_valid(new_url: str) -> bool:
    return is_new_url_valid(new_url)


def crawling_redirects_to_other_url(url1: str, url2: str) -> bool:
    return redirects_to_other_url(url1, url2)


############
# DOWNLOAD #
############

def crawling_get_content_from_url(url: str) -> tuple[str, bytes | None] | None:
    return get_content_from_url(url)
