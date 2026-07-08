import re
from urllib.parse import urlparse, ParseResult, parse_qs, urlencode

from bs4 import BeautifulSoup, SoupStrainer, Comment
from bs4 import element as el

from scheduling.utils.date_utils import get_current_year
from crawling.workflows.download.download_content import get_url_redirection
from scheduling.utils.string_search import has_any_of_words
from crawling.utils.string_utils import remove_unsafe_chars
from crawling.utils.url_utils import is_internal_link, get_clean_full_url, \
    replace_scheme_and_hostname, get_path, MAX_URL_LENGTH

CONFESSIONS_OR_SCHEDULES_MENTIONS = [
    'confession',
    'confessions',
    'confesser',
    'reconciliation',
    'reconcilier',
    'penitence',
    'sacrement',
    'sacrements',
    'pardon',
    'horaire',
    'horaires',
    'noel',
    'careme',
    'paques',
    'pascal',
    'priere',
    'prier',
    'etapes',
    'paroisse',
    'spirituelle',
    'info',
    'infos',
    'informations',
    'informer',
    'vivre',
    'demarche',
    'demarches',
    'agenda',
    'feuille',
    'annonces',
]

IGNORED_EXTENSIONS = [
    # word
    '.docx',

    # images
    '.jpg',
    '.jpeg',
    '.png',

    # media
    '.mp3',
    '.m4a',
    '.wav',
    '.mp4',
    '.mov',
    '.avi',
    '.mkv',
    '.webm',
    '.flv',
    '.wmv',
    '.wma',
    '.flac'

    # calendar
    '.ics',

    # archive
    '.zip',
]


def might_be_confession_link(path, text):
    path = path[:-1] if path.endswith('/') else path
    last_part_of_path = path.split('/')[-1] if '/' in path else path

    if has_any_of_words(last_part_of_path, CONFESSIONS_OR_SCHEDULES_MENTIONS) \
            or has_any_of_words(text, CONFESSIONS_OR_SCHEDULES_MENTIONS):
        return True

    return False


def clean_url_query(url_parsed: ParseResult):
    query = parse_qs(url_parsed.query, keep_blank_values=True)

    # We remove share parameter (share=twitter, share=facebook...)
    query.pop('share', None)

    # We remove calendar parameter (outlook-ical=1 ...)
    query.pop('ical', None)
    query.pop('outlook-ical', None)

    url_parsed = url_parsed._replace(query=urlencode(query, True))

    return url_parsed.geturl()


def is_forbidden(url_parsed: ParseResult, home_url: str, forbidden_outer_paths: set[str],
                 path_redirection: dict[str, str], forbidden_paths: set[str]) -> bool:
    url_path = str(url_parsed.path)
    url_full_path = f"{url_path}?{url_parsed.query}" if url_parsed.query else ''
    for forbidden_path in forbidden_paths:
        if url_path.startswith(forbidden_path) or url_full_path.startswith(forbidden_path):
            return True

    considered_paths = [url_path] + ([url_full_path] if url_full_path else [])

    if url_path.startswith('/category'):
        # Sometimes, the path starts with '/category' and we want to check if it is forbidden
        # by removing '/category' from the beginning of the path
        # This is useful for some CMS like WordPress
        considered_paths.append(url_path.replace('/category', ''))

    home_url_path = get_path(home_url)
    for accepted_home_word in ['accueil', 'home']:
        if home_url_path.endswith(f'/{accepted_home_word}'):
            home_url_path = home_url_path[:-len(accepted_home_word) - 1]
    if home_url_path:
        for considered_path in considered_paths:
            if considered_path.startswith(home_url_path):
                return False

    if forbidden_outer_paths:
        for forbidden_outer_path in forbidden_outer_paths:
            for considered_path in considered_paths:
                if considered_path.startswith(forbidden_outer_path):
                    return True

        # if we are in a multi-website domain (e.g. diocese), we forbid paths that contains
        # the words 'paroisse', since it's likely another parish website
        if 'paroisse' in url_path:
            if url_path not in path_redirection:
                path_redirection[url_path] = get_url_redirection(url_parsed.geturl())

            new_url = path_redirection[url_path]
            new_url_parsed = urlparse(new_url)

            # Get the path with redirection
            if new_url_parsed.path != url_path:
                return is_forbidden(new_url_parsed, home_url, forbidden_outer_paths,
                                    path_redirection, forbidden_paths)

            return True

    return False


def is_obsolete_path(path: str) -> bool:
    last_segment = path.rstrip('/').split('/')[-1]
    current_year = get_current_year()
    for year in range(2000, current_year):
        if f'{year}' in last_segment:
            for w in re.split(r'\D', last_segment):
                if w == f'{year}':
                    return True
    return False


def get_a_tags(element: el) -> list[el.Tag]:
    a_tags = []
    for item in element:
        inner_a_tags = item.find_all('a')
        if inner_a_tags:
            a_tags.extend(inner_a_tags)
        else:
            a_tags.append(item)

    return a_tags


def get_links(element: el, home_url: str, aliases_domains: set[str],
              forbidden_outer_paths: set[str],
              path_redirection: dict[str, str],
              forbidden_paths: set[str]
              ) -> set[str]:
    results = set()

    for link in get_a_tags(element):
        if not link.has_attr('href'):
            continue

        full_url = str(link['href'])
        try:
            url_parsed = urlparse(full_url)
        except ValueError:
            print(f'cannot parse url {full_url}')
            continue

        # If the link is like "sacrements.html", we build it from any home_url we have
        if not url_parsed.netloc:
            full_url = replace_scheme_and_hostname(url_parsed, new_url=home_url)
            url_parsed = urlparse(full_url)

        # We ignore external links (ex: facebook page...)
        if not is_internal_link(full_url, url_parsed, aliases_domains):
            continue

        # We ignore forbidden paths and their children
        if is_forbidden(url_parsed, home_url, forbidden_outer_paths, path_redirection,
                        forbidden_paths):
            continue

        full_url = get_clean_full_url(full_url, keep_trailing_slash=True)
        url_parsed = urlparse(full_url)

        if len(full_url) > MAX_URL_LENGTH:
            # We ignore links that are too long
            continue

        # If the link contains parameters we remove the non-useful ones
        if url_parsed.query:
            full_url = clean_url_query(url_parsed)
            url_parsed = urlparse(full_url)

        # If this is a link to an image or a calendar we ignore it
        if any(url_parsed.path.endswith(extension) for extension in IGNORED_EXTENSIONS):
            continue

        # Extract link text
        all_strings = link.find_all(string=lambda t: not isinstance(t, Comment),
                                    recursive=True)
        text = ' '.join(all_strings).rstrip()
        text = remove_unsafe_chars(text)

        if is_obsolete_path(url_parsed.path):
            continue

        if might_be_confession_link(url_parsed.path, text):
            results.add(full_url)

    return results


def parse_content_links(content, home_url: str, aliases_domains: set[str],
                        forbidden_outer_paths: set[str], path_redirection: dict[str, str],
                        forbidden_paths: set[str]
                        ) -> set[str]:
    try:
        element = BeautifulSoup(content, 'html.parser', parse_only=SoupStrainer('a'))
    except Exception as e:
        print(e)
        return set()

    links = get_links(element, home_url, aliases_domains, forbidden_outer_paths,
                      path_redirection, forbidden_paths)

    return links


def remove_http_https_duplicate(
        extracted_html_list_by_link: dict[str, tuple[list[str], bytes | None]]
) -> dict[str, tuple[list[str], bytes | None]]:
    """If links appear twice in given list with different scheme, we keep only https"""
    d = {}
    for link, extracted_html_list in extracted_html_list_by_link.items():
        link_with_https = link.replace('http://', 'https://')
        link_parsed = urlparse(link)
        d.setdefault(link_with_https, {})[link_parsed.scheme] = extracted_html_list

    results = {}
    for link_with_https, extracted_html_list_by_scheme in d.items():
        if 'https' in extracted_html_list_by_scheme:
            results[link_with_https] = extracted_html_list_by_scheme['https']
        else:
            scheme, extracted_html_list = list(extracted_html_list_by_scheme.items())[0]
            original_link = link_with_https.replace('https://', f'{scheme}://')
            results[original_link] = extracted_html_list

    return results
