from django.contrib.gis.geos import Point

from registry.models import City
from registry.utils.gouv_fr_utils import GouvFrCommune

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
