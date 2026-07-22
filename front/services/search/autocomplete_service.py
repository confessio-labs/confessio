import asyncio
from dataclasses import dataclass
from json import JSONDecodeError
from statistics import mean
from typing import Optional
from uuid import UUID

import httpx
from django.contrib.gis.db.models import Collect
from django.contrib.gis.db.models.functions import Distance, Centroid
from django.contrib.gis.geos import Point
from django.contrib.postgres.lookups import Unaccent
from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Case, ExpressionWrapper, FloatField, Q, When
from django.db.models import F
from django.db.models import Value
from django.db.models.functions import Greatest, Ln, Replace, Lower
from django.urls import reverse
from httpx import RequestError

from front.utils.department_utils import get_departments_context
from front.utils.distance_utils import distance
from registry.models import City, Parish, Church, Website
from registry.utils.city_name_utils import normalize_city_name
from registry.utils.string_utils import get_string_similarity
from scheduling.utils.string_search import unhyphen_content, normalize_content

MAX_AUTOCOMPLETE_RESULTS = 15
HALF_LIFE_DISTANCE = 5000

# Every municipality result shares the same url (around_place_view), and get_aggregated_response
# dedups on url, so only one city can ever reach the dropdown. Cities are ranked by the SQL score
# below, which balances name, proximity and population far better than get_score() does at
# national scale, so we pick the winner here rather than letting sort_results() re-rank them.
MAX_CITY_RESULTS = 1

# Weights of the City ranking score. Tuned on 62 labelled (query, user location) -> expected city
# cases: population had to be raised (8 -> 20) and trigram similarity lowered (30 -> 10), because
# similarity mechanically penalizes long names ('aix en provence' scores 0.25 against the query
# 'aix', while a 352-inhabitant hamlet named 'Aix' scores 1.0).
PREFIX_WEIGHT = 50.0
SIMILARITY_WEIGHT = 10.0
GEO_WEIGHT = 12.0
POPULATION_WEIGHT = 20.0
# ln(2_500_000), a bit above the most populated commune, so that s_pop stays in [0, 1]
MAX_LN_POPULATION = 14.73
# Distance at which the proximity score halves. Django's Distance() on this geometry compiles to
# ST_DistanceSphere, which returns METERS, so a raw 1/(1+d) would pin s_geo to ~0 everywhere
# (1/144886 at 145 km) and waste the whole geo term.
GEO_HALF_LIFE_METERS = 50000.0


@dataclass
class AutocompleteResult:
    type: str
    name: str
    context: str
    url: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    uuid: UUID | None = None
    church_uuid: UUID | None = None

    @classmethod
    def from_parish(cls, parish: Parish) -> 'AutocompleteResult':
        # TODO save context in parish, and create a command to fill it

        longitudes = []
        latitudes = []
        cities = set()
        zipcodes = set()
        church_uuids = set()
        for church in parish.churches.all():
            longitudes.append(church.location.x)
            latitudes.append(church.location.y)
            if church.city:
                cities.add(church.city)
            if church.zipcode:
                zipcodes.add(church.zipcode)
            church_uuids.add(church.uuid)
        latitude = longitude = None
        if latitudes and longitudes:
            latitude = mean(latitudes)
            longitude = mean(longitudes)

        if len(zipcodes) == 0:
            context = None
        elif len(cities) == 1 and len(zipcodes) == 1:
            context = f'{zipcodes.pop()} {cities.pop()}'
        else:
            context = get_departments_context(zipcodes)

        church_uuid = None
        if len(church_uuids) == 1:
            church_uuid = church_uuids.pop()

        return AutocompleteResult(
            type='parish',
            name=parish.name,
            context=context,
            url=reverse('website_view', kwargs={'website_uuid': parish.website.uuid}),
            latitude=latitude,
            longitude=longitude,
            uuid=parish.uuid,
            church_uuid=church_uuid,
        )

    @classmethod
    def from_website(cls, website: Website) -> 'AutocompleteResult':
        # TODO save context in website, and create a command to fill it

        longitudes = []
        latitudes = []
        cities = set()
        zipcodes = set()
        church_uuids = set()
        for parish in website.parishes.all():
            for church in parish.churches.all():
                longitudes.append(church.location.x)
                latitudes.append(church.location.y)
                if church.city:
                    cities.add(church.city)
                if church.zipcode:
                    zipcodes.add(church.zipcode)
                church_uuids.add(church.uuid)
        latitude = longitude = None
        if latitudes and longitudes:
            latitude = mean(latitudes)
            longitude = mean(longitudes)

        if len(zipcodes) == 0:
            context = None
        elif len(cities) == 1 and len(zipcodes) == 1:
            context = f'{zipcodes.pop()} {cities.pop()}'
        else:
            context = get_departments_context(zipcodes)

        church_uuid = None
        if len(church_uuids) == 1:
            church_uuid = church_uuids.pop()

        return AutocompleteResult(
            type='parish',
            name=website.name,
            context=context,
            url=reverse('website_view', kwargs={'website_uuid': website.uuid}),
            latitude=latitude,
            longitude=longitude,
            uuid=website.uuid,
            church_uuid=church_uuid,
        )

    @classmethod
    def from_church(cls, church: Church) -> 'AutocompleteResult':
        if not church.zipcode:
            context = None
        elif church.city and church.zipcode:
            context = f'{church.zipcode} {church.city}'
        else:
            context = get_departments_context({church.zipcode})

        return AutocompleteResult(
            type='church',
            name=church.name,
            context=context,
            url=reverse('website_view', kwargs={'website_uuid': church.parish.website.uuid}),
            latitude=church.location.y,
            longitude=church.location.x,
            uuid=church.uuid,
            church_uuid=church.uuid,
        )

    @classmethod
    def from_city(cls, city: City) -> 'AutocompleteResult':
        return AutocompleteResult(
            type='municipality',
            name=city.name,
            context=city.zipcode,
            latitude=city.location.y,
            longitude=city.location.x,
            url=reverse('around_place_view'),
            uuid=city.uuid,
        )


async def get_city_response(query: str, latitude: float | None, longitude: float | None
                            ) -> list[AutocompleteResult]:
    """Municipality autocomplete from the local City table, replacing get_data_gouv_response().

    Not wired in yet: it returns nothing until one_shot__seed_cities has run, so it is switched
    on from get_aggregated_response() only once the target database has been seeded.
    """
    if not query or len(query) > 200 or len(query) < 3 or not query[0].isalnum():
        return []

    query_term = normalize_city_name(query)

    cities = City.objects.filter(
        Q(name_norm__trigram_similar=query_term) | Q(name_norm__startswith=query_term)
    ).annotate(
        s_prefix=Case(
            When(name_norm__startswith=query_term, then=Value(1.0)),
            default=Value(0.0),
            output_field=FloatField(),
        ),
        s_sim=TrigramSimilarity('name_norm', query_term),
        s_pop=ExpressionWrapper(
            Ln(Greatest(F('population'), Value(1))) / Value(MAX_LN_POPULATION),
            output_field=FloatField(),
        ),
    )

    if latitude is not None and longitude is not None:
        user_location = Point(longitude, latitude, srid=4326)
        cities = cities.annotate(
            distance=Distance('location', user_location),
        ).annotate(
            s_geo=ExpressionWrapper(
                Value(1.0) / (Value(1.0) + F('distance') / Value(GEO_HALF_LIFE_METERS)),
                output_field=FloatField(),
            ),
        )
    else:
        cities = cities.annotate(s_geo=Value(0.0, output_field=FloatField()))

    cities = cities.annotate(
        final_score=ExpressionWrapper(
            F('s_prefix') * Value(PREFIX_WEIGHT)
            + F('s_sim') * Value(SIMILARITY_WEIGHT)
            + F('s_geo') * Value(GEO_WEIGHT)
            + F('s_pop') * Value(POPULATION_WEIGHT),
            output_field=FloatField(),
        )
    ).order_by('-final_score')[:MAX_CITY_RESULTS]

    return [AutocompleteResult.from_city(city) async for city in cities]


async def get_data_gouv_response(query: str, latitude: float | None, longitude: float | None
                                 ) -> list[AutocompleteResult]:
    """Municipality autocomplete through the external data.gouv completion API.

    Still the one wired into get_aggregated_response(). It is meant to be replaced by
    get_city_response(), which is why it is kept here: switching back is a one-line change.
    """
    if not query or len(query) > 200 or len(query) < 3 or not query[0].isalnum():
        return []

    # https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/autocompletion/
    url = f'https://data.geopf.fr/geocodage/completion/'
    lonlat_dict = {}
    if latitude is not None and longitude is not None:
        lonlat_dict = {'lonlat': f'{longitude},{latitude}'}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, params={
                    'text': query,
                    'maximumResponses': MAX_AUTOCOMPLETE_RESULTS,
                    'type': 'PositionOfInterest',
                    'poiType': 'commune',
                } | lonlat_dict)
    except RequestError as e:
        print(f'Exception in get_data_gouv_response: {e}')
        print(f"Query: {query}")
        from core.otel.metrics_service import metrics_service
        metrics_service.increment_warning_counter('data_gouv_error')
        return []

    if response.status_code != 200:
        print(f'Error in get_data_gouv_response: {response.status_code}')
        print(f"Query: {query}, Response code {response.status_code}, "
              f"Response text: {response.text}")
        from core.otel.metrics_service import metrics_service
        metrics_service.increment_warning_counter('data_gouv_error')
        return []

    try:
        data = response.json()
    except JSONDecodeError as e:
        print(f'JSON decode error in get_data_gouv_response: {e}')
        print(f'Query: {query}, Response text: {response.text}')
        from core.otel.metrics_service import metrics_service
        metrics_service.increment_warning_counter('data_gouv_error')
        return []

    if 'results' not in data or not data['results']:
        return []

    results = []
    for result in data['results']:
        results.append(AutocompleteResult(
            type='municipality',
            name=result['names'][0],
            context=result.get('zipcode', ''),
            latitude=result['y'],
            longitude=result['x'],
            url=reverse('around_place_view'),
        ))

    return results


async def get_parish_by_name_response(query, latitude: float | None,
                                      longitude: float | None) -> list[AutocompleteResult]:
    query_term = unhyphen_content(normalize_content(query))
    parishes = Parish.objects.select_related('website').prefetch_related('churches').annotate(
        search_name=Replace(Unaccent(Lower('name')), Value('-'), Value(' '))
    ).filter(website__is_active=True, search_name__contains=query_term) \
        .only("name",
              "website__uuid",
              )

    if latitude is not None and longitude is not None:
        user_location = Point(longitude, latitude, srid=4326)
        parishes = parishes.annotate(
            centroid=Centroid(Collect('churches__location')),
        ).annotate(
            distance=Distance('centroid', user_location),
        ).order_by(F('distance').asc(nulls_last=True))

    parishes = parishes[:MAX_AUTOCOMPLETE_RESULTS]

    return [AutocompleteResult.from_parish(parish) async for parish in parishes]


async def get_website_by_name_response(query, latitude: float | None,
                                       longitude: float | None) -> list[AutocompleteResult]:
    query_term = unhyphen_content(normalize_content(query))
    websites = Website.objects.prefetch_related('parishes__churches').annotate(
        search_name=Replace(Unaccent(Lower('name')), Value('-'), Value(' '))
    ).filter(is_active=True, search_name__contains=query_term) \
        .only("name",
              "uuid",
              )

    if latitude is not None and longitude is not None:
        user_location = Point(longitude, latitude, srid=4326)
        websites = websites.annotate(
            centroid=Centroid(Collect('parishes__churches__location')),
        ).annotate(
            distance=Distance('centroid', user_location),
        ).order_by(F('distance').asc(nulls_last=True))

    websites = websites[:MAX_AUTOCOMPLETE_RESULTS]

    return [AutocompleteResult.from_website(website) async for website in websites]


async def get_church_by_name_response(query, latitude: float | None,
                                      longitude: float | None) -> list[AutocompleteResult]:
    query_term = unhyphen_content(normalize_content(query))
    churches = Church.objects.select_related('parish__website').annotate(
        search_name=Replace(Unaccent(Lower('name')), Value('-'), Value(' '))
    ).filter(is_active=True, parish__website__is_active=True,
             search_name__contains=query_term) \
        .only("name",
              "city",
              "zipcode",
              "location",
              "parish__website__uuid",
              )

    if latitude is not None and longitude is not None:
        user_location = Point(longitude, latitude, srid=4326)
        churches = churches.annotate(
            distance=Distance('location', user_location)
        ).order_by(F('distance').asc(nulls_last=True))

    churches = churches[:MAX_AUTOCOMPLETE_RESULTS]

    return [AutocompleteResult.from_church(church) async for church in churches]


def get_score(query, latitude: float | None, longitude: float | None,
              result: AutocompleteResult) -> float:
    string_similarity = get_string_similarity(query, result.name)
    d = 0.0
    if latitude is not None and longitude is not None \
            and result.latitude is not None and result.longitude is not None:
        d = distance(latitude, longitude, result.latitude, result.longitude)

    return string_similarity * HALF_LIFE_DISTANCE / (HALF_LIFE_DISTANCE + d)


def sort_results(query, latitude: float | None, longitude: float | None,
                 results: list[AutocompleteResult]) -> list[AutocompleteResult]:
    if not results:
        return []

    tuples = zip(map(lambda r: get_score(query, latitude, longitude, r), results), results)
    sorted_tuples = sorted(tuples, key=lambda t: t[0], reverse=True)
    _, sorted_values = zip(*sorted_tuples)

    return sorted_values


async def get_aggregated_response(query, latitude: float | None, longitude: float | None
                                  ) -> list[AutocompleteResult]:
    # To switch to the local City table, call get_city_response() here instead. Do it only once
    # one_shot__seed_cities has run on the target database, otherwise municipality suggestions
    # silently disappear until it does.
    data_gouv_results, website_by_name_results, parish_by_name_results, church_by_name_results = \
        await asyncio.gather(
            get_data_gouv_response(query, latitude, longitude),
            get_website_by_name_response(query, latitude, longitude),
            get_parish_by_name_response(query, latitude, longitude),
            get_church_by_name_response(query, latitude, longitude),
        )

    sorted_results = sort_results(
        query, latitude, longitude,
        data_gouv_results + website_by_name_results
        + parish_by_name_results + church_by_name_results)

    seen_urls = set()
    unique_results = [
        r for r in sorted_results
        if r.url not in seen_urls and not seen_urls.add(r.url)
    ]

    return unique_results[:MAX_AUTOCOMPLETE_RESULTS]
