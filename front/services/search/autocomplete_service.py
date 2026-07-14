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
from django.db.models import F
from django.db.models import Value
from django.db.models.functions import Replace, Lower
from django.urls import reverse
from httpx import RequestError

from front.utils.department_utils import get_departments_context
from front.utils.distance_utils import distance
from registry.models import Parish, Church, Website
from registry.utils.string_utils import get_string_similarity
from scheduling.utils.string_search import unhyphen_content, normalize_content

MAX_AUTOCOMPLETE_RESULTS = 15
HALF_LIFE_DISTANCE = 5000


@dataclass
class AutocompleteResult:
    type: str
    name: str
    context: str
    url: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    uuid: UUID | None = None

    @classmethod
    def from_parish(cls, parish: Parish) -> 'AutocompleteResult':
        # TODO save context in parish, and create a command to fill it

        longitudes = []
        latitudes = []
        cities = set()
        zipcodes = set()
        for church in parish.churches.all():
            longitudes.append(church.location.x)
            latitudes.append(church.location.y)
            if church.city:
                cities.add(church.city)
            if church.zipcode:
                zipcodes.add(church.zipcode)
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

        return AutocompleteResult(
            type='parish',
            name=parish.name,
            context=context,
            url=reverse('website_view', kwargs={'website_uuid': parish.website.uuid}),
            latitude=latitude,
            longitude=longitude,
            uuid=parish.uuid,
        )

    @classmethod
    def from_website(cls, website: Website) -> 'AutocompleteResult':
        # TODO save context in website, and create a command to fill it

        longitudes = []
        latitudes = []
        cities = set()
        zipcodes = set()
        for parish in website.parishes.all():
            for church in parish.churches.all():
                longitudes.append(church.location.x)
                latitudes.append(church.location.y)
                if church.city:
                    cities.add(church.city)
                if church.zipcode:
                    zipcodes.add(church.zipcode)
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

        return AutocompleteResult(
            type='parish',
            name=website.name,
            context=context,
            url=reverse('website_view', kwargs={'website_uuid': website.uuid}),
            latitude=latitude,
            longitude=longitude,
            uuid=website.uuid,
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
        )


async def get_data_gouv_response(query: str, latitude: float | None, longitude: float | None
                                 ) -> list[AutocompleteResult]:
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
