from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from httpx import HTTPError, InvalidURL, Response

from core.utils.log_utils import info
from crawling.workflows.download.google_calendar import is_google_calendar_url, \
    get_google_calendar_html
from crawling.workflows.refine.pdf_utils import extract_text_from_pdf_bytes
from crawling.utils.url_utils import get_domain, are_similar_urls, replace_scheme_and_hostname, \
    replace_http_with_https

DOWNLOAD_TIMEOUT = 40
TIMEOUT = httpx.Timeout(
    connect=DOWNLOAD_TIMEOUT / 4,
    read=DOWNLOAD_TIMEOUT / 2,
    write=DOWNLOAD_TIMEOUT / 8,
    pool=DOWNLOAD_TIMEOUT / 8,
)
MAX_SIZE = 1_000_000


def get_headers():
    return {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
    }


def get_content_length(url):
    info(f'getting content length from url {url}')

    headers = get_headers()
    try:
        with httpx.Client() as client:
            r = client.get(url, headers=headers, timeout=TIMEOUT)
            r.raise_for_status()
    except (httpx.HTTPError, InvalidURL) as e:
        info(e)
        return None

    content_length = r.headers.get('Content-Length')
    if not content_length:
        total_size = 0
        for chunk in r.iter_bytes(chunk_size=8192):
            total_size += len(chunk)
            if total_size > MAX_SIZE:
                info("File size exceeds limit. Download aborted.")
                return None

        return total_size

    return int(content_length)


def count_bad_chars(content: str) -> int:
    if not content:
        return 0

    return content.count('�')


def get_text_with_right_encoding(response: Response) -> str:
    """
    Example of url with misleading encoding:
    https://www.paroisses-cote-de-jade.fr/horaires_des_messes_et_permanences_519.htm
    """
    text_auto = response.text
    try:
        text_cp1252 = response.content.decode("cp1252")
    except UnicodeDecodeError:
        return text_auto

    if count_bad_chars(text_cp1252) < count_bad_chars(text_auto):
        return text_cp1252

    return text_auto


def get_content_from_url(url: str) -> tuple[str, bytes | None] | None:
    # Google Calendar embeds are JavaScript shells with no event data; fetch their public
    # iCalendar feed instead and render it to HTML for the regular pruning/parsing pipeline.
    if is_google_calendar_url(url):
        html = get_google_calendar_html(url)
        return (html, None) if html else None

    # Handle heavy pdf files
    if url.endswith('.pdf'):
        content_length = get_content_length(url)
        if content_length is None:
            info(f'could not get content length from url {url}')
            return None

        if content_length > MAX_SIZE:
            info(f'content length is {content_length}, too large (>1MB)')
            return None
        else:
            info(f'content length is {content_length}')

    info(f'getting content from url {url}')

    headers = get_headers()
    try:
        with httpx.Client() as client:
            r = client.get(url, headers=headers, timeout=TIMEOUT, follow_redirects=True)
    except (HTTPError, InvalidURL) as e:
        info(e)
        return None

    if r.status_code != 200:
        info(f'got status code {r.status_code}')

        return None

    if is_pdf(r):
        return extract_text_from_pdf_bytes(r.content), r.content

    return get_text_with_right_encoding(r), None


def get_meta_refresh_tag_content(soup: BeautifulSoup) -> Optional[str]:
    for meta_tag in soup.find_all('meta'):
        if meta_tag.get('http-equiv', '').lower() == 'refresh':
            return meta_tag.get('content', '')

    return None


def get_meta_refresh_redirect(soup: BeautifulSoup) -> Optional[str]:
    meta_refresh_content = get_meta_refresh_tag_content(soup)
    if meta_refresh_content:
        # The content usually looks like "0; url=http://example.com"
        parts = meta_refresh_content.split(';')
        if len(parts) > 1:
            second_part = parts[1].replace('URL=', 'url=')
            if 'url=' in second_part:
                return second_part.split('url=')[1].strip()

    return None


def is_pdf(r: Response) -> bool:
    content_type = r.headers.get("Content-Type", r.headers.get("content-type", ""))
    content_disposition = r.headers.get("content-disposition", "")
    if content_type.lower().startswith("application/pdf") or \
            content_disposition.lower().endswith(".pdf"):
        return True

    return False


def get_url_aliases(url, already_seen: set | None = None
                    ) -> tuple[list[tuple[str, str]], Optional[str]]:
    if already_seen and url in already_seen:
        info(f'url {url} already seen, stopping there')
        return [], f'url {url} already seen'

    info(f'getting url aliases for {url}')

    headers = get_headers()
    try:
        with httpx.Client() as client:
            r = client.get(url, headers=headers, follow_redirects=False, timeout=TIMEOUT)
    except (HTTPError, InvalidURL) as e:
        attempt_with_https = replace_http_with_https(url)
        if attempt_with_https:
            info(f'error with http, trying https: {e}')
            return get_url_aliases(attempt_with_https, (already_seen or set()) | {url})

        return [], str(e)

    aliases = [(url, get_domain(url))]
    redirect_url = None

    if r.status_code in [301, 302] and 'location' in r.headers:
        redirect_url = r.headers['location']
    elif r.status_code == 200:
        if is_pdf(r):
            # We don't want to parse pdf files
            return aliases, None

        try:
            soup = BeautifulSoup(r.text, 'html.parser')
        except Exception as e:
            info(e)
            return aliases, str(e)
        redirect_url = get_meta_refresh_redirect(soup)

    if redirect_url:
        redirect_url_parsed = urlparse(redirect_url)

        # If the link is like "sacrements.html", we build it from the url we have
        if not redirect_url_parsed.netloc:
            redirect_url = replace_scheme_and_hostname(redirect_url_parsed, new_url=url)

        url_aliases, error_message = get_url_aliases(redirect_url,
                                                     (already_seen or set()) | {url})
        if not url_aliases:
            info(f'tried to follow redirect location {redirect_url} but got error {error_message}')
        else:
            aliases.extend(url_aliases)

    return aliases, None


def redirects_to_other_url(url1: str, url2: str) -> bool:
    if are_similar_urls(url1, url2):
        return True

    aliases, _ = get_url_aliases(url1)
    for url, domain in aliases:
        if are_similar_urls(url, url2):
            return True
    return False


def get_url_redirection(url: str) -> str | None:
    aliases, _ = get_url_aliases(url)
    if not aliases:
        return None

    return str(aliases[-1][0])
