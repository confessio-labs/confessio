import random
import re
import time
from typing import Callable

import requests
from requests import RequestException, JSONDecodeError

OVERPASS_URL = 'https://overpass-api.de/api/interpreter'
OVERPASS_STATUS_URL = 'https://overpass-api.de/api/status'
# overpass-api.de returns HTTP 406 to requests carrying a default library User-Agent
USER_AGENT = 'Confessio/1.0 (+https://confessio.fr; city locations)'

# The public instance gets transiently overloaded in two ways: 429 when no query slot is free, and
# 504 with 'Dispatcher_Client::request_read_and_idx::timeout. The server is probably too busy' when
# the dispatcher refuses the query before running it. Both clear up within a minute or two, so we
# wait long enough rather than dropping a whole department.
BACKOFF_SECONDS = [15.0, 30.0, 60.0, 90.0, 120.0]
MAX_WAIT_SECONDS = 180.0
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}

# The admin_centre (or label) member node of a commune's boundary relation is the OSM position
# of the town center; the node itself rarely carries ref:INSEE, so fetch the relations with
# their member lists and join node -> role -> ref:INSEE client-side.
ADMIN_CENTRE_QUERY = """
[out:json][timeout:180];
rel["boundary"="administrative"]["admin_level"="8"]["ref:INSEE"~"^{prefix}"]->.communes;
.communes out body;
(
  node(r.communes:"admin_centre");
  node(r.communes:"label");
);
out body;
"""


def build_admin_centre_query(insee_prefix: str) -> str:
    return ADMIN_CENTRE_QUERY.format(prefix=insee_prefix)


def _find_member_node(relation: dict, nodes_by_id: dict) -> dict | None:
    for role in ['admin_centre', 'label']:
        for member in relation.get('members', []):
            if member.get('type') == 'node' and member.get('role') == role:
                node = nodes_by_id.get(member.get('ref'))
                if node is not None:
                    return node

    return None


def parse_admin_centres(data: dict) -> dict[str, tuple[float, float]]:
    """Extract insee_code -> (latitude, longitude) of each commune's admin centre node."""
    nodes_by_id = {}
    relations = []
    for element in data.get('elements', []):
        if element.get('type') == 'node':
            nodes_by_id[element['id']] = element
        elif element.get('type') == 'relation':
            relations.append(element)

    admin_centres = {}
    for relation in relations:
        insee_code = relation.get('tags', {}).get('ref:INSEE', None)
        if not insee_code:
            continue

        node = _find_member_node(relation, nodes_by_id)
        if node is None or node.get('lat') is None or node.get('lon') is None:
            continue

        admin_centres[insee_code] = (node['lat'], node['lon'])

    return admin_centres


SLOTS_AVAILABLE_PATTERN = re.compile(r'\d+ slots? available now')
SLOT_WAIT_PATTERN = re.compile(r'Slot available after:.*?in (\d+) seconds')


def _parse_slot_wait(status_text: str) -> float | None:
    """Seconds to wait before a query slot frees up, as announced by /api/status."""
    if SLOTS_AVAILABLE_PATTERN.search(status_text):
        return 0.0

    waits = [int(wait) for wait in SLOT_WAIT_PATTERN.findall(status_text)]
    if not waits:
        return None

    return min(min(waits) + 2.0, MAX_WAIT_SECONDS)


def _fetch_slot_wait(log: Callable[[str], None]) -> float | None:
    try:
        response = requests.get(OVERPASS_STATUS_URL, headers={'User-Agent': USER_AGENT},
                                timeout=15)
    except RequestException as e:
        log(f'overpass status request failed: {e}')
        return None

    if response.status_code != 200:
        log(f'overpass status returned {response.status_code}')
        return None

    return _parse_slot_wait(response.text)


def _wait_seconds(response, attempt: int, log: Callable[[str], None]) -> float:
    # A 429 means no slot is free: /api/status tells us exactly how long until one is.
    if response is not None and response.status_code == 429:
        slot_wait = _fetch_slot_wait(log)
        if slot_wait is not None:
            return max(slot_wait, 5.0)

    retry_after = response.headers.get('Retry-After') if response is not None else None
    if retry_after:
        try:
            return min(float(int(retry_after)), MAX_WAIT_SECONDS)
        except ValueError:
            pass

    base = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]

    return base * random.uniform(0.8, 1.2)


def fetch_admin_centres(insee_prefix: str, max_attempts: int = 6,
                        log: Callable[[str], None] = print
                        ) -> dict[str, tuple[float, float]] | None:
    query = build_admin_centre_query(insee_prefix)
    for attempt in range(max_attempts):
        attempt_context = f'prefix {insee_prefix} (attempt {attempt + 1}/{max_attempts})'
        response = None
        try:
            response = requests.post(OVERPASS_URL, data={'data': query},
                                     headers={'User-Agent': USER_AGENT}, timeout=200)
        except RequestException as e:
            log(f'overpass request failed for {attempt_context}: {e}')

        if response is not None and response.status_code == 200:
            try:
                data = response.json()
            except JSONDecodeError as e:
                log(f'invalid overpass json for {attempt_context}: {e}')
            else:
                # Overpass reports server-side failures as a remark in an otherwise valid 200
                # answer, with an empty element list: retry instead of returning zero centres.
                remark = data.get('remark', None)
                if not remark or 'error' not in remark.lower():
                    return parse_admin_centres(data)

                log(f'overpass remark for {attempt_context}: {remark}')
        elif response is not None and response.status_code in TRANSIENT_STATUS_CODES:
            log(f'overpass returned {response.status_code} for {attempt_context}')
        elif response is not None:
            log(f'overpass returned {response.status_code} for prefix {insee_prefix}, giving up')
            return None

        if attempt < max_attempts - 1:
            wait = _wait_seconds(response, attempt, log)
            log(f'waiting {wait:.0f}s before retrying prefix {insee_prefix}')
            time.sleep(wait)

    return None
