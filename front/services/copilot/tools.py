"""Core logic for the copilot's tools (plain sync functions, independent of PydanticAI).

The agent wrappers live in agent.py; keeping the logic here makes it testable without
constructing an LLM model. Autonomous tools read only; proposed tools mutate and are only
invoked after the admin approves in the UI.
"""
import datetime
import decimal
import os
import uuid as uuid_lib
from urllib.parse import quote

import requests
from django.contrib.gis.geos import Point
from django.db import connections

from registry.models import Church, Diocese, Parish, Website

MAX_SQL_ROWS = 200
MAX_CELL_LEN = 2000
MAX_PAGE_CHARS = 6000

READONLY_ALIAS = 'copilot_readonly'


# --------------------------------------------------------------------------- #
# Autonomous (read-only) tools                                                 #
# --------------------------------------------------------------------------- #

def _jsonable(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, str) and len(value) > MAX_CELL_LEN:
            return value[:MAX_CELL_LEN] + '…'
        return value
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, uuid_lib.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return str(value)[:MAX_CELL_LEN]


def run_readonly_sql(query: str, max_rows: int = MAX_SQL_ROWS) -> dict:
    """Run a single read-only SELECT/WITH statement on the copilot_readonly connection.

    Returns {columns, rows, row_count, truncated} or {error}. The Postgres role is read-only
    (SELECT-only grants + default_transaction_read_only + statement_timeout), so this is the
    real safety barrier; the check below is just a friendly guard.
    """
    stripped = query.strip().rstrip(';').strip()
    if not stripped:
        return {'error': 'Empty query.'}
    first_word = stripped.split(None, 1)[0].lower()
    if first_word not in ('select', 'with'):
        return {'error': 'Only read-only SELECT/WITH queries are allowed.'}

    if READONLY_ALIAS not in connections.databases:
        return {'error': 'The read-only copilot database connection is not configured.'}

    try:
        with connections[READONLY_ALIAS].cursor() as cursor:
            cursor.execute(stripped)
            columns = [col[0] for col in cursor.description] if cursor.description else []
            raw_rows = cursor.fetchmany(max_rows + 1)
    except Exception as e:  # noqa: BLE001 - surface any DB error back to the agent as text
        return {'error': f'{type(e).__name__}: {e}'}

    truncated = len(raw_rows) > max_rows
    rows = [[_jsonable(v) for v in row] for row in raw_rows[:max_rows]]
    return {
        'columns': columns,
        'rows': rows,
        'row_count': len(rows),
        'truncated': truncated,
    }


def fetch_url(url: str) -> dict:
    """Visit a URL and return its text content (truncated). Never raises: returns {error} on
    timeout / 4xx / 5xx / non-text content."""
    from crawling.public_service import crawling_get_content_from_url
    try:
        result = crawling_get_content_from_url(url)
    except Exception as e:  # noqa: BLE001
        return {'url': url, 'error': f'{type(e).__name__}: {e}'}
    if result is None:
        return {'url': url, 'error': 'Could not fetch the page (timeout, 4xx/5xx, or too large).'}

    text, pdf_bytes = result
    text = text or ''
    return {
        'url': url,
        'is_pdf': pdf_bytes is not None,
        'truncated': len(text) > MAX_PAGE_CHARS,
        'content': text[:MAX_PAGE_CHARS],
    }


def google_search(query: str) -> dict:
    """Google Programmable Search. Returns {results:[{title, link, snippet}]} or {error}."""
    from registry.utils.google_search_api_utils import get_google_search_results
    try:
        results = get_google_search_results(query)
    except Exception as e:  # noqa: BLE001
        return {'error': f'{type(e).__name__}: {e}'}
    return {'results': [
        {'title': r.title, 'link': r.link, 'display_link': r.display_link, 'snippet': r.snippet}
        for r in results
    ]}


def google_maps_search(query: str) -> dict:
    """Google Maps Places text search. Returns {results:[{name, address, location}]} or {error}."""
    api_key = os.getenv('GOOGLE_MAPS_API_KEY')
    if not api_key:
        return {'error': 'GOOGLE_MAPS_API_KEY is not configured.'}
    url = ('https://maps.googleapis.com/maps/api/place/textsearch/json'
           f'?query={quote(query)}&key={api_key}')
    try:
        response = requests.get(url, timeout=20)
        data = response.json()
    except Exception as e:  # noqa: BLE001
        return {'error': f'{type(e).__name__}: {e}'}

    status = data.get('status')
    if status not in ('OK', 'ZERO_RESULTS'):
        detail = data.get('error_message', '')
        return {'error': f'Google Maps API status: {status}. {detail}'.strip()}

    results = []
    for item in (data.get('results') or [])[:10]:
        loc = item.get('geometry', {}).get('location', {})
        results.append({
            'name': item.get('name'),
            'address': item.get('formatted_address'),
            'location': {'lat': loc.get('lat'), 'lng': loc.get('lng')},
            'place_id': item.get('place_id'),
        })
    return {'results': results}


# --------------------------------------------------------------------------- #
# Proposed (mutating) tools — only run after the admin approves                #
# --------------------------------------------------------------------------- #

def _get(model, label, **kwargs):
    try:
        return model.objects.get(**kwargs)
    except model.DoesNotExist:
        raise ValueError(f'No {label} found for {kwargs}.')


def do_assign_website(discussion_uuid: str, website_uuid: str) -> dict:
    from front.models import CopilotDiscussion
    website = _get(Website, 'website', uuid=website_uuid)
    CopilotDiscussion.objects.filter(uuid=discussion_uuid).update(website=website)
    return {'assigned_website_uuid': str(website.uuid), 'website_name': website.name}


def do_add_church(parish_uuid: str, name: str, city: str | None = None,
                  zipcode: str | None = None, address: str | None = None,
                  latitude: float | None = None, longitude: float | None = None) -> dict:
    parish = _get(Parish, 'parish', uuid=parish_uuid)
    location = Point(longitude, latitude, srid=4326) \
        if latitude is not None and longitude is not None else None
    church = Church.objects.create(
        name=name, parish=parish, city=city, zipcode=zipcode, address=address, location=location)
    return {'created_church_uuid': str(church.uuid), 'name': church.name}


def do_update_church(church_uuid: str, name: str | None = None, city: str | None = None,
                     zipcode: str | None = None, address: str | None = None,
                     latitude: float | None = None, longitude: float | None = None,
                     parish_uuid: str | None = None, is_active: bool | None = None) -> dict:
    church = _get(Church, 'church', uuid=church_uuid)
    if name is not None:
        church.name = name
    if city is not None:
        church.city = city
    if zipcode is not None:
        church.zipcode = zipcode
    if address is not None:
        church.address = address
    if latitude is not None and longitude is not None:
        church.location = Point(longitude, latitude, srid=4326)
    if parish_uuid is not None:
        church.parish = _get(Parish, 'parish', uuid=parish_uuid)
    if is_active is not None:
        church.is_active = is_active
    church.save()
    return {'updated_church_uuid': str(church.uuid), 'name': church.name}


def do_delete_church(church_uuid: str) -> dict:
    church = _get(Church, 'church', uuid=church_uuid)
    name = church.name
    church.delete()
    return {'deleted_church_uuid': church_uuid, 'name': name}


def do_add_parish(diocese_uuid: str, name: str, website_uuid: str | None = None) -> dict:
    diocese = _get(Diocese, 'diocese', uuid=diocese_uuid)
    website = _get(Website, 'website', uuid=website_uuid) if website_uuid else None
    parish = Parish.objects.create(name=name, diocese=diocese, website=website)
    return {'created_parish_uuid': str(parish.uuid), 'name': parish.name}


def do_update_parish(parish_uuid: str, name: str | None = None,
                     website_uuid: str | None = None, diocese_uuid: str | None = None) -> dict:
    parish = _get(Parish, 'parish', uuid=parish_uuid)
    if name is not None:
        parish.name = name
    if website_uuid is not None:
        parish.website = _get(Website, 'website', uuid=website_uuid)
    if diocese_uuid is not None:
        parish.diocese = _get(Diocese, 'diocese', uuid=diocese_uuid)
    parish.save()
    return {'updated_parish_uuid': str(parish.uuid), 'name': parish.name}


def do_delete_parish(parish_uuid: str) -> dict:
    parish = _get(Parish, 'parish', uuid=parish_uuid)
    name = parish.name
    parish.delete()
    return {'deleted_parish_uuid': parish_uuid, 'name': name}


def do_add_website(name: str, home_url: str) -> dict:
    website = Website.objects.create(name=name, home_url=home_url)
    return {'created_website_uuid': str(website.uuid), 'name': website.name}


def do_update_website(website_uuid: str, name: str | None = None, home_url: str | None = None,
                      is_active: bool | None = None,
                      enabled_for_crawling: bool | None = None) -> dict:
    website = _get(Website, 'website', uuid=website_uuid)
    if name is not None:
        website.name = name
    if home_url is not None:
        website.home_url = home_url
    if is_active is not None:
        website.is_active = is_active
    if enabled_for_crawling is not None:
        website.enabled_for_crawling = enabled_for_crawling
    website.save()
    return {'updated_website_uuid': str(website.uuid), 'name': website.name}


def do_delete_website(website_uuid: str) -> dict:
    website = _get(Website, 'website', uuid=website_uuid)
    name = website.name
    website.delete()
    return {'deleted_website_uuid': website_uuid, 'name': name}


def do_trigger_recrawl(website_uuid: str) -> dict:
    from crawling.public_service import crawling_crawl_website
    website = _get(Website, 'website', uuid=website_uuid)
    crawling_crawl_website(website)
    return {'recrawl_enqueued_for': str(website.uuid), 'website_name': website.name}
