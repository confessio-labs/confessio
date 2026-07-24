from collections import Counter
from urllib.parse import urlparse, ParseResult

from crawling.utils.string_utils import remove_unsafe_chars


MAX_URL_LENGTH = 512


def get_domain(url):
    url_parsed = urlparse(url)

    return url_parsed.netloc


def get_path(url):
    url_parsed = urlparse(url)

    return url_parsed.path


def get_full_path(url):
    url_parsed = urlparse(url)
    if url_parsed.query:
        return f"{url_parsed.path if url_parsed.path else '/'}?{url_parsed.query}"
    return url_parsed.path


def path_key(url: str) -> str:
    # group query-param variants of the same page; treat /a and /a/ as one path
    return get_path(url).rstrip('/')


def select_next_link_to_visit(links_to_visit, visited_links) -> str:
    """Return the next queued link, round-robin across paths (query string ignored).

    Primary key: how many pages of that path we have *already visited* (ascending), so every
    distinct path is visited once before any path's query-param variants are revisited — no single
    group (e.g. `/agenda/?mois=...`) can monopolise the visit budget. Secondary key: how many
    variants of that path are still *queued* (ascending), so among equally-visited paths the rarer
    one comes first. Ties break FIFO: `min` is stable and `links_to_visit` iterates in insertion
    order, so the earliest-queued link wins.

    `links_to_visit` must be an order-preserving iterable (a dict used as an ordered set);
    `visited_links` is the set of already-visited links (must not yet include the returned link).
    """
    visited_path_counts = Counter(path_key(link) for link in visited_links)
    queued_path_counts = Counter(path_key(link) for link in links_to_visit)
    return min(
        links_to_visit,
        key=lambda link: (visited_path_counts[path_key(link)],
                          queued_path_counts[path_key(link)]),
    )


def replace_scheme_and_hostname(url_parsed: ParseResult, new_url: str) -> str:
    new_url_parsed = urlparse(new_url)

    url_parsed = url_parsed._replace(scheme=new_url_parsed.scheme)
    url_parsed = url_parsed._replace(netloc=new_url_parsed.netloc)

    return url_parsed.geturl()


def get_clean_full_url(url, keep_trailing_slash: bool = False) -> str:
    url = remove_unsafe_chars(url)
    url_parsed = urlparse(url)

    url_parsed = clean_parsed_url(url_parsed, keep_trailing_slash)

    return url_parsed.geturl()


def clean_parsed_url(url_parsed: ParseResult, keep_trailing_slash: bool) -> ParseResult:
    path = url_parsed.path
    if not keep_trailing_slash:
        if path.endswith('/'):
            url_parsed = url_parsed._replace(path=path[:-1])

    url_parsed = url_parsed._replace(fragment='')

    netloc = url_parsed.netloc
    if netloc.endswith(' '):
        url_parsed = url_parsed._replace(netloc=netloc.strip())

    return url_parsed


def is_internal_link(url: str, url_parsed: ParseResult, aliases_domains: set[str]):
    if url_parsed.scheme not in ['http', 'https']:
        return False

    if url.startswith('#'):
        # link on same page
        return False

    if not is_similar_to_domains(url_parsed.netloc, aliases_domains):
        # external link
        return False

    return True


def is_similar_to_domains(domain: str, domains: set[str]):
    for d in domains:
        if are_similar_domains(domain, d):
            return True

    return False


def get_canonical_domain(domain: str):
    return domain.replace('www.', '')\
        .replace('ww2.', '')\
        .split('.')[:-1]


def are_similar_domains(domain1: str, domain2: str):
    return get_canonical_domain(domain1) == get_canonical_domain(domain2)


def have_similar_domain(url1: str, url2: str):
    domain1 = urlparse(url1).netloc
    domain2 = urlparse(url2).netloc

    return are_similar_domains(domain1, domain2)


def are_similar_path(url1: str, url2: str):
    url1_parsed = urlparse(url1)
    url2_parsed = urlparse(url2)

    path1 = url1_parsed.path
    if path1.endswith('/'):
        path1 = path1[:-1]

    path2 = url2_parsed.path
    if path2.endswith('/'):
        path2 = path2[:-1]

    return path1 == path2


def are_similar_urls(url1: str, url2: str):
    # if urls are the same, they are similar
    if url1 == url2:
        return True

    if have_similar_domain(url1, url2) and are_similar_path(url1, url2):
        return True

    return False


def replace_http_with_https(url: str) -> str | None:
    url_parsed = urlparse(url)
    if url_parsed.scheme == 'http':
        url_parsed = url_parsed._replace(scheme='https')
        return url_parsed.geturl()

    return None
