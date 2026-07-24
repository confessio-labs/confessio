import time

import requests
from requests import RequestException, JSONDecodeError

OVERPASS_URL = 'https://overpass-api.de/api/interpreter'
# overpass-api.de returns HTTP 406 to requests carrying a default library User-Agent
USER_AGENT = 'Confessio/1.0 (+https://confessio.fr; city locations)'

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


def _retry_after_seconds(response, attempt: int) -> float:
    retry_after = response.headers.get('Retry-After') if response is not None else None
    if retry_after:
        try:
            return min(float(int(retry_after)), 60.0)
        except ValueError:
            pass

    return min(10.0 * 2 ** attempt, 60.0)


def fetch_admin_centres(insee_prefix: str,
                        max_retries: int = 3) -> dict[str, tuple[float, float]] | None:
    query = build_admin_centre_query(insee_prefix)
    for attempt in range(max_retries + 1):
        response = None
        try:
            response = requests.post(OVERPASS_URL, data={'data': query},
                                     headers={'User-Agent': USER_AGENT}, timeout=200)
        except RequestException as e:
            print(f'overpass request failed for prefix {insee_prefix}:', e)

        if response is not None and response.status_code == 200:
            try:
                return parse_admin_centres(response.json())
            except JSONDecodeError as e:
                print(f'invalid overpass json for prefix {insee_prefix}:', e)
        elif response is not None:
            print(f'overpass returned {response.status_code} for prefix {insee_prefix}')

        if attempt < max_retries:
            time.sleep(_retry_after_seconds(response, attempt))

    return None
