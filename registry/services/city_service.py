import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable
from uuid import UUID

from django.contrib.gis.geos import Point
from django.db import transaction

from front.utils.department_utils import get_department
from registry.models import City
from registry.utils.city_name_utils import slugify_city_name
from registry.utils.geo_utils import get_geo_distance
from registry.utils.gouv_fr_utils import GouvFrCommune
from registry.utils.overpass_utils import fetch_admin_centres

# Paris, Marseille and Lyon are returned with all their arrondissement zipcodes: use the
# conventional generic code instead of the first arrondissement's.
MAIN_ZIPCODE_BY_INSEE = {
    '75056': '75000',  # Paris
    '13055': '13000',  # Marseille
    '69123': '69000',  # Lyon
}

# Above this population, the extra zipcodes of a commune are district codes and the main one
# ends in '00' (Aix-en-Provence is 13100, not 13080). Below it, extra zipcodes usually come from
# a commune nouvelle merger, where '00' means nothing and the lowest code is as good as any
# (Château-Arnoux-Saint-Auban really is 04160, not 04600).
LARGE_CITY_POPULATION = 30000


def get_main_zipcode(insee_code: str, zipcodes: list[str], population: int) -> str | None:
    if insee_code in MAIN_ZIPCODE_BY_INSEE:
        return MAIN_ZIPCODE_BY_INSEE[insee_code]

    if not zipcodes:
        return None

    sorted_zipcodes = sorted(zipcodes)
    if population >= LARGE_CITY_POPULATION:
        return next((z for z in sorted_zipcodes if z.endswith('00')), sorted_zipcodes[0])

    return sorted_zipcodes[0]


def build_city(commune: GouvFrCommune) -> City | None:
    population = commune.population or 0
    zipcode = get_main_zipcode(commune.code, commune.zipcodes, population)
    if not zipcode or not commune.centre:
        return None

    coordinates = commune.centre.get('coordinates', None)
    if not coordinates or len(coordinates) != 2:
        return None

    # GeoJSON coordinates are [longitude, latitude]
    longitude, latitude = coordinates

    return City(
        insee_code=commune.code,
        name=commune.nom,
        zipcode=zipcode,
        population=population,
        location=Point(longitude, latitude, srid=4326),
    )


def upsert_cities(cities: list[City]):
    City.objects.bulk_create(
        cities,
        batch_size=1000,
        update_conflicts=True,
        unique_fields=['insee_code'],
        update_fields=['name', 'zipcode', 'population', 'location'],
    )


# Pause between two Overpass queries: the public instance rate-limits back-to-back requests.
OVERPASS_SLEEP_SECONDS = 5

# The busy spells of the public instance last a minute or two: let it breathe before the second
# pass over the prefixes that failed.
OVERPASS_COOLDOWN_SECONDS = 60

# Below this distance the OSM position and the stored one are considered the same point.
SAME_POINT_METERS = 1


@dataclass
class CityLocationUpdateStats:
    nb_cities: int
    nb_matched: int
    nb_unmatched: int
    nb_moved: int
    nb_moved_over_1km: int
    nb_moved_over_5km: int
    top_movers: list[tuple[str, str, float]]  # (insee_code, name, distance in meters)
    failed_prefixes: list[str]


def _fetch_admin_centres_by_prefix(prefixes: list[str], log: Callable[[str], None]
                                   ) -> tuple[dict[str, tuple[float, float]], list[str]]:
    osm_positions = {}
    failed_prefixes = []
    for i, prefix in enumerate(prefixes):
        if i > 0:
            time.sleep(OVERPASS_SLEEP_SECONDS)
        admin_centres = fetch_admin_centres(prefix, log=log)
        if admin_centres is None:
            failed_prefixes.append(prefix)
            log(f'prefix {prefix}: overpass query failed ({i + 1}/{len(prefixes)})')
            continue

        osm_positions.update(admin_centres)
        log(f'prefix {prefix}: {len(admin_centres)} admin centres ({i + 1}/{len(prefixes)})')

    return osm_positions, failed_prefixes


def update_city_locations(departments: list[str] | None = None, dry_run: bool = False,
                          log: Callable[[str], None] = print) -> CityLocationUpdateStats:
    """Move every city to the OSM admin centre (town center) of its commune.

    Cities without an OSM admin centre keep their current location (the commune centroid
    from geo.api.gouv.fr) and are only counted.
    """
    cities = list(City.objects.all())
    if departments:
        cities = [c for c in cities if get_department(c.insee_code) in departments]

    prefixes = sorted(set(get_department(city.insee_code) for city in cities))
    osm_positions, failed_prefixes = _fetch_admin_centres_by_prefix(prefixes, log)
    if failed_prefixes:
        log(f'{len(failed_prefixes)} prefixes failed ({" ".join(failed_prefixes)}), retrying them '
            f'in {OVERPASS_COOLDOWN_SECONDS}s...')
        time.sleep(OVERPASS_COOLDOWN_SECONDS)
        retried_positions, failed_prefixes = _fetch_admin_centres_by_prefix(failed_prefixes, log)
        osm_positions.update(retried_positions)

    moved = []
    distances = []
    nb_matched = 0
    nb_unmatched = 0
    for city in cities:
        if city.insee_code not in osm_positions:
            # cities of a failed prefix are neither matched nor unmatched
            if get_department(city.insee_code) not in failed_prefixes:
                nb_unmatched += 1
            continue

        nb_matched += 1
        latitude, longitude = osm_positions[city.insee_code]
        new_location = Point(longitude, latitude, srid=4326)
        distance = get_geo_distance(city.location, new_location)
        if distance < SAME_POINT_METERS:
            continue

        distances.append((city.insee_code, city.name, distance))
        city.location = new_location
        moved.append(city)

    if not dry_run and moved:
        City.objects.bulk_update(moved, ['location'], batch_size=1000)

    return CityLocationUpdateStats(
        nb_cities=len(cities),
        nb_matched=nb_matched,
        nb_unmatched=nb_unmatched,
        nb_moved=len(moved),
        nb_moved_over_1km=sum(1 for _, _, d in distances if d > 1000),
        nb_moved_over_5km=sum(1 for _, _, d in distances if d > 5000),
        top_movers=sorted(distances, key=lambda t: -t[2])[:10],
        failed_prefixes=failed_prefixes,
    )


# Appended to the slug of the cities that share a name, in this order: the most populated one
# keeps the bare slug, the others get the department, then the zipcode if they also share the
# department ('le-havre', then 'le-havre-76', then 'le-havre-76600').
SLUG_DISCRIMINATORS = [
    lambda city: get_department(city.zipcode),
    lambda city: city.zipcode,
]


def _assign_slugs(base: str, candidate: str, cities: list[City], depth: int,
                  slugs: dict[UUID, str]):
    """Give `candidate` to the most populated city, and a more precise slug to the others."""
    winner = min(cities, key=lambda c: (-c.population, c.insee_code))
    slugs[winner.uuid] = candidate

    rest = [c for c in cities if c.uuid != winner.uuid]
    if not rest:
        return

    if depth >= len(SLUG_DISCRIMINATORS):
        # unreachable: compute_city_slugs() rejects same-slug-same-zipcode cities beforehand
        raise ValueError(f'no discriminator left to slugify {candidate}: '
                         f'{[(c.insee_code, c.name, c.zipcode) for c in cities]}')

    groups = defaultdict(list)
    for city in rest:
        # always suffix the base slug, otherwise depth 2 would give 'le-havre-76-76600'
        groups[f'{base}-{SLUG_DISCRIMINATORS[depth](city)}'].append(city)

    for next_candidate, group in groups.items():
        _assign_slugs(base, next_candidate, group, depth + 1, slugs)


def compute_city_slugs(cities: list[City]) -> dict[UUID, str]:
    cities_by_base_slug = defaultdict(list)
    for city in cities:
        cities_by_base_slug[slugify_city_name(city.name)].append(city)

    # Two cities with the same name and the same zipcode are a data anomaly: there is nothing
    # left to tell them apart, so we refuse to slugify them rather than pick an arbitrary winner.
    cities_by_slug_and_zipcode = defaultdict(list)
    for base, group in cities_by_base_slug.items():
        for city in group:
            cities_by_slug_and_zipcode[(base, city.zipcode)].append(city)
    for (base, zipcode), group in cities_by_slug_and_zipcode.items():
        if len(group) > 1:
            raise ValueError(f'several cities share the slug {base} and the zipcode {zipcode}: '
                             f'{[(c.insee_code, c.name) for c in group]}')

    slugs = {}
    for base, group in cities_by_base_slug.items():
        _assign_slugs(base, base, group, 0, slugs)

    if len(set(slugs.values())) != len(slugs):
        raise ValueError('computed city slugs are not unique')

    return slugs


def refresh_city_slugs(dry_run: bool = False) -> tuple[int, int]:
    """Recompute every city slug, and return (nb_cities, nb_changed)."""
    cities = list(City.objects.all())
    slugs = compute_city_slugs(cities)
    changed = [c for c in cities if c.slug != slugs[c.uuid]]

    if not dry_run and changed:
        with transaction.atomic():
            # free the old values first: a slug moving from one city to another would otherwise
            # hit the unique constraint mid-update
            City.objects.filter(uuid__in=[c.uuid for c in changed]).update(slug=None)
            for city in changed:
                city.slug = slugs[city.uuid]
            City.objects.bulk_update(changed, ['slug'], batch_size=1000)

    return len(cities), len(changed)
