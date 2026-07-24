import time

from pydantic import BaseModel, Field

from core.utils.ram_utils import print_memory_usage
from crawling.utils.url_utils import get_clean_full_url, get_path, get_full_path, \
    select_next_link_to_visit
from crawling.workflows.crawl.extract_links import parse_content_links, remove_http_https_duplicate
from crawling.workflows.crawl.extract_widgets import extract_widgets, BaseWidget, \
    detect_google_calendar_urls, parse_html
from crawling.workflows.download.download_content import get_content_from_url, get_url_aliases, \
    DOWNLOAD_TIMEOUT
from crawling.workflows.scrape.download_refine_and_extract import get_extracted_v2_html_list
from scheduling.utils.html_utils import split_lines

MAX_VISITED_LINKS = 50


class CrawlingResult(BaseModel, frozen=True):
    confession_pages: dict[str, tuple[list[str], bytes | None]] = Field(default_factory=dict)
    visited_links_count: int = 0
    error_detail: str | None = None
    widgets: list[BaseWidget] = Field(default_factory=list)


def forbid_diocese_home_links(diocese_url: str, aliases_domains: set[str],
                              path_redirection: dict[str, str]) -> set[str]:
    content = get_content_from_url(diocese_url)
    if content is None:
        print('no content for diocese home url')
        return set()
    html_content, _ = content

    new_links = parse_content_links(html_content, diocese_url, aliases_domains, set(),
                                    path_redirection, set())
    forbidden_paths = set()
    for link in new_links:
        path = get_path(link)
        full_path = get_full_path(link)
        if path:
            forbidden_paths.add(path)
        if full_path:
            forbidden_paths.add(full_path)

    print(f'found {len(forbidden_paths)} paths to forbid: {forbidden_paths}')

    return forbidden_paths


def get_new_url_and_aliases(url: str) -> tuple[str, set[str], str | None]:
    url_aliases, error_message = get_url_aliases(url)
    if not url_aliases:
        return url, set(), error_message

    new_url = get_clean_full_url(url_aliases[-1][0])

    return new_url, set([alias[1] for alias in url_aliases]), None


def is_new_url_valid(new_url: str) -> bool:
    not_eligible_urls = [
        'google.com/sorry',
        'google.com/v3/signin',
        'accounts.google.com',
        'wp-admin/install.php',
    ]
    for not_eligible_url in not_eligible_urls:
        if not_eligible_url in new_url:
            return False

    return True


class CrawlingTimeoutError(Exception):
    pass


def search_for_confession_pages(home_url, aliases_domains: set[str],
                                forbidden_outer_paths: set[str],
                                path_redirection: dict[str, str],
                                forbidden_paths: set[str]
                                ) -> CrawlingResult:
    deadline = time.time() + (1 + MAX_VISITED_LINKS) * (1 + DOWNLOAD_TIMEOUT)

    visited_links = set()
    # dict used as an ordered set: preserves first-discovery order (FIFO) for the selection policy
    links_to_visit = {home_url: None}
    extracted_html_seen = set()

    error_detail = None

    content_by_url = {}
    all_widgets = []
    while len(links_to_visit) > 0 and len(visited_links) < MAX_VISITED_LINKS:
        if deadline is not None and time.time() > deadline:
            raise CrawlingTimeoutError()

        print_memory_usage()

        link = select_next_link_to_visit(links_to_visit, visited_links)
        del links_to_visit[link]
        visited_links.add(link)

        content = get_content_from_url(link)
        if content is None:
            # something went wrong (e.g. 404), we just ignore this page
            print(f'no content for {link}')
            continue
        html_content, pdf_bytes = content

        # Looking if new confession part is found
        extracted_html_list = get_extracted_v2_html_list(html_content)
        if extracted_html_list and any(extracted_html not in extracted_html_seen
                                       for extracted_html in extracted_html_list or []):
            content_by_url[link] = (extracted_html_list, pdf_bytes)
            extracted_html_seen.update(set(extracted_html_list))

        # Looking for new links to visit
        new_links = parse_content_links(html_content, home_url, aliases_domains,
                                        forbidden_outer_paths, path_redirection,
                                        forbidden_paths)

        # Parse the page once and share the soup: BeautifulSoup('html.parser') is super-linear
        # on large pages, so widget + calendar detection must not each re-parse the same HTML.
        page_soup = parse_html(html_content)

        # Looking for widgets
        widgets = extract_widgets(page_soup) if page_soup is not None else []
        if widgets:
            print(f'found {len(widgets)} widgets for {link}: {widgets}')
            all_widgets.extend(widgets)

        # Google Calendar embeds live on a different host and are not <a> links, so they are
        # never discovered by parse_content_links; detect and enqueue them explicitly.
        if page_soup is not None:
            for calendar_url in detect_google_calendar_urls(page_soup):
                if calendar_url not in visited_links:
                    links_to_visit[calendar_url] = None

        for new_link in new_links:
            if new_link not in visited_links:
                links_to_visit[new_link] = None

    if len(visited_links) == MAX_VISITED_LINKS:
        error_detail = f'Reached limit of {MAX_VISITED_LINKS} visited links.'

    return CrawlingResult(
        confession_pages=remove_http_https_duplicate(content_by_url),
        visited_links_count=len(visited_links),
        error_detail=error_detail,
        widgets=all_widgets,
    )


if __name__ == '__main__':
    # home_url = 'https://www.eglise-saintgermaindespres.fr/'
    # home_url = 'https://www.saintjacquesduhautpas.com/'
    # home_url = 'https://paroisses-amplepuis-thizy.blogspot.fr/'
    # home_url = 'https://paroissesaintbruno.pagesperso-orange.fr/'
    # home_url_ = 'https://paroissecroixrousse.fr/'
    # home_url_ = 'https://www.espace-saint-ignace.fr/'
    # home_url_ = 'https://www.paroisse-st-martin-largentiere.fr'
    home_url_ = 'https://www.paroissesaintleger.fr'
    confession_pages = search_for_confession_pages(home_url_,
                                                   {'www.paroissesaintleger.fr'},
                                                   set(), {}, set())
    for cr in confession_pages.confession_pages:
        print(f'url: {cr}')
        for paragraph in confession_pages.confession_pages[cr][0]:
            print('<<<')
            for line in split_lines(paragraph):
                print(line)
            print('>>>')
