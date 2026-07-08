import re

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from crawling.workflows.download.google_calendar import is_google_calendar_url


class OClocherWidget(BaseModel):
    organization_id: str


class ContactWidget(BaseModel, frozen=True):
    email: str = Field(max_length=100)


BaseWidget = OClocherWidget | ContactWidget


def parse_html(html: str) -> BeautifulSoup | None:
    try:
        return BeautifulSoup(html, 'html.parser')
    except Exception as e:
        print(e)
        return None


def extract_oclocher_widgets(soup: BeautifulSoup) -> list[OClocherWidget]:
    widgets = []

    for iframes in soup.find_all('iframe'):
        src_url = iframes.get('src')
        if not src_url:
            continue

        match = re.search(r"widget.oclocher.app/organization/([^/]+)/", src_url)
        if not match:
            continue
        organization_id = match.group(1)
        widgets.append(OClocherWidget(organization_id=organization_id))

    return widgets


def extract_contact_widgets(soup: BeautifulSoup) -> list[ContactWidget]:
    widgets = []

    # look for mailto links in the page and extract the email addresses
    potential_emails = set()
    for mailto_links in soup.find_all('a', href=True):
        href = mailto_links['href']
        if href.startswith('mailto:'):
            potential_emails.add(href[len('mailto:'):])

    # search for email addresses in the text of the page using a regex
    email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    for text in list(soup.stripped_strings) + list(potential_emails):
        for match in re.findall(email_regex, text):
            if len(match) <= 100:  # only consider emails with a reasonable length
                widgets.append(ContactWidget(email=match))

    return list(set(widgets))  # remove duplicates


def extract_widgets(soup: BeautifulSoup) -> list[BaseWidget]:
    return extract_oclocher_widgets(soup) + extract_contact_widgets(soup)


def detect_google_calendar_urls(soup: BeautifulSoup) -> set[str]:
    """Find embedded public Google Calendar URLs (cross-domain <iframe>/<a>) on a page."""
    urls = set()
    for iframe in soup.find_all('iframe'):
        src = iframe.get('src')
        if src and is_google_calendar_url(src):
            urls.add(src.strip())
    for link in soup.find_all('a', href=True):
        href = link['href']
        if is_google_calendar_url(href):
            urls.add(href.strip())

    return urls
