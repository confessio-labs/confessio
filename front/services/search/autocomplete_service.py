import asyncio
from dataclasses import dataclass
from math import log
from statistics import mean
from typing import Optional
from uuid import UUID

from django.contrib.gis.db.models import Collect
from django.contrib.gis.db.models.functions import Distance, Centroid
from django.contrib.gis.geos import Point
from django.contrib.postgres.search import TrigramSimilarity, TrigramWordSimilarity
from django.db import connections
from django.db.models import Case, ExpressionWrapper, FloatField, Q, When
from django.db.models import F
from django.db.models import Value
from django.db.models.functions import Coalesce, Exp, Greatest, Least, Ln
from django.urls import reverse

from front.utils.autocomplete_constants import (
    GEO_HALF_LIFE_METERS, GEO_POP_GATE_THRESHOLD, GEO_WEIGHT, MAX_AUTOCOMPLETE_RESULTS,
    MAX_LN_POPULARITY, MAX_LN_POPULATION, POPULARITY_WEIGHT, POPULATION_WEIGHT, PREFIX_WEIGHT,
    SIMILARITY_WEIGHT, SUBSTRING_WEIGHT, TYPE_BOOSTS, WORD_SIMILARITY_WEIGHT)
from front.utils.department_utils import get_departments_context
from registry.models import City, Parish, Church, Website
from registry.utils.city_name_utils import normalize_city_name


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
            url=reverse('city_view', kwargs={'city_slug': city.slug}),
            uuid=city.uuid,
        )


def _log_normalized_expression(field: str, max_ln: float):
    """ln(field) rescaled into [0, 1], shared by the live fetchers and the tuning pools.

    Coalesce and Greatest map NULL and 0 onto ln(1) = 0. Both are defensive rather than
    load-bearing (neither column is nullable, and Postgres' GREATEST already ignores NULLs), but
    they keep the expression correct if a caller ever drops the is_active filters that make the
    website joins inner. Least caps the result at 1: unlike a commune's population, a rolling
    traffic counter has no natural ceiling.
    """
    normalized = ExpressionWrapper(
        Ln(Greatest(Coalesce(F(field), Value(0)), Value(1))) / Value(max_ln),
        output_field=FloatField(),
    )
    return ExpressionWrapper(Least(Value(1.0), normalized), output_field=FloatField())


def build_population_expression():
    """Demographic size of a municipality — the city flavour of popularity."""
    return _log_normalized_expression('population', MAX_LN_POPULATION)


def build_popularity_expression():
    """Traffic of a parish/website/church. Each owns its `nb_recent_hits`, hence no join path."""
    return _log_normalized_expression('nb_recent_hits', MAX_LN_POPULARITY)


def annotate_search_score(qs, query_term: str, user_point: Point | None, geo_field: str,
                          type_boost: float, population_expression=None,
                          popularity_expression=None):
    """Annotate the shared autocomplete ranking score, computed entirely in SQL.

    All four sources get the exact same formula so their `final_score` values are comparable
    and the merge is a plain sort. `geo_field` names a geometry column or annotation
    ('location', or a pre-annotated 'centroid'). A source supplies exactly one of the two size
    expressions — demographic for City, traffic for the other three — and the one it leaves out
    scores 0, so the formula can simply add both terms.
    """
    qs = qs.annotate(
        s_prefix=Case(
            When(name_norm__startswith=query_term, then=Value(1.0)),
            default=Value(0.0),
            output_field=FloatField(),
        ),
        s_substr=Case(
            When(name_norm__contains=query_term, then=Value(1.0)),
            default=Value(0.0),
            output_field=FloatField(),
        ),
        s_sim=TrigramSimilarity('name_norm', query_term),
        s_word=TrigramWordSimilarity(query_term, 'name_norm'),
        s_population=population_expression if population_expression is not None
        else Value(0.0, output_field=FloatField()),
        s_popularity=popularity_expression if popularity_expression is not None
        else Value(0.0, output_field=FloatField()),
    )

    if user_point is not None:
        # Distance() on these geometries compiles to ST_DistanceSphere -> METERS. Coalesce
        # guards NULL geometries (parish without churches): NULL would poison the whole sum.
        qs = qs.annotate(
            distance=Distance(geo_field, user_point),
        ).annotate(
            s_geo=Coalesce(
                Exp(ExpressionWrapper(
                    F('distance') * Value(-log(2) / GEO_HALF_LIFE_METERS),
                    output_field=FloatField(),
                )),
                Value(0.0),
                output_field=FloatField(),
            ),
        )
    else:
        qs = qs.annotate(s_geo=Value(0.0, output_field=FloatField()))

    # Geo and both size signals count in proportion to string-match quality (full weight once the
    # best string signal reaches GEO_POP_GATE_THRESHOLD): tie-breakers among good matches, never a
    # substitute for matching.
    quality_gate = Least(
        Value(1.0),
        Greatest(F('s_prefix'), F('s_substr'), F('s_word')) / Value(GEO_POP_GATE_THRESHOLD),
    )
    return qs.annotate(
        final_score=ExpressionWrapper(
            F('s_prefix') * Value(PREFIX_WEIGHT)
            + F('s_substr') * Value(SUBSTRING_WEIGHT)
            + F('s_sim') * Value(SIMILARITY_WEIGHT)
            + F('s_word') * Value(WORD_SIMILARITY_WEIGHT)
            + (F('s_geo') * Value(GEO_WEIGHT)
               + F('s_population') * Value(POPULATION_WEIGHT)
               + F('s_popularity') * Value(POPULARITY_WEIGHT))
            * quality_gate
            + Value(type_boost),
            output_field=FloatField(),
        )
    ).order_by('-final_score')


ScoredResults = list[tuple[float, AutocompleteResult]]


def _scored_then_hydrated(scoring_qs, hydration_qs, factory) -> ScoredResults:
    """Rank on a narrow projection, then load only the kept rows.

    The scoring query evaluates every matching row; selecting full joined rows there made broad
    queries sort megabytes before the LIMIT ('saint' matches 21k churches, and the joined rows
    are ~4 KB wide). Fetch (uuid, final_score) first, then hydrate the 15 winners with the
    relations and .only() column set the AutocompleteResult factories need.
    """
    scored = list(scoring_qs.values_list('uuid', 'final_score')[:MAX_AUTOCOMPLETE_RESULTS])
    rows = {obj.uuid: obj for obj in hydration_qs.filter(uuid__in=[u for u, _ in scored])}
    return [(score, factory(rows[uuid])) for uuid, score in scored if uuid in rows]


def get_city_response(query_term: str, user_point: Point | None) -> ScoredResults:
    # Single-phase: one table, no join amplification (62 ms on the broadest real query).
    cities = City.objects.filter(
        Q(name_norm__trigram_similar=query_term) | Q(name_norm__startswith=query_term)
    )
    cities = annotate_search_score(
        cities, query_term, user_point, 'location', TYPE_BOOSTS['municipality'],
        population_expression=build_population_expression(),
    )[:MAX_AUTOCOMPLETE_RESULTS]

    return [(city.final_score, AutocompleteResult.from_city(city)) for city in cities]


def long_name_predicate(query_term: str) -> Q:
    """Retrieval for long names (parish, website, church).

    `contains` keeps the exact-substring matches long names need (plain trigram similarity can
    not fire for a short query against a 40-char name); `trigram_word_similar` adds the fuzzy
    matches: 26% of recorded municipality picks were trigram-only matches, a match type these
    sources could not produce before.
    """
    return Q(name_norm__contains=query_term) | Q(name_norm__trigram_word_similar=query_term)


def get_parish_by_name_response(query_term: str,
                                user_point: Point | None) -> ScoredResults:
    scoring = annotate_search_score(
        Parish.objects.filter(website__is_active=True)
        .filter(long_name_predicate(query_term))
        .annotate(centroid=Centroid(Collect('churches__location'))),
        query_term, user_point, 'centroid', TYPE_BOOSTS['parish'],
        popularity_expression=build_popularity_expression())
    hydration = Parish.objects.select_related('website').prefetch_related('churches') \
        .only('name', 'website__uuid')

    return _scored_then_hydrated(scoring, hydration, AutocompleteResult.from_parish)


def get_website_by_name_response(query_term: str,
                                 user_point: Point | None) -> ScoredResults:
    scoring = annotate_search_score(
        Website.objects.filter(is_active=True).filter(long_name_predicate(query_term))
        .annotate(centroid=Centroid(Collect('parishes__churches__location'))),
        query_term, user_point, 'centroid', TYPE_BOOSTS['parish'],
        popularity_expression=build_popularity_expression())
    hydration = Website.objects.prefetch_related('parishes__churches').only('name', 'uuid')

    return _scored_then_hydrated(scoring, hydration, AutocompleteResult.from_website)


def get_church_by_name_response(query_term: str,
                                user_point: Point | None) -> ScoredResults:
    scoring = annotate_search_score(
        Church.objects.filter(is_active=True, parish__website__is_active=True)
        .filter(long_name_predicate(query_term)),
        query_term, user_point, 'location', TYPE_BOOSTS['church'],
        popularity_expression=build_popularity_expression())
    hydration = Church.objects.select_related('parish__website') \
        .only('name', 'city', 'zipcode', 'location', 'parish__website__uuid')

    return _scored_then_hydrated(scoring, hydration, AutocompleteResult.from_church)


def _fetch_in_thread(fetcher, query_term: str, user_point: Point | None) -> ScoredResults:
    # Each fetcher runs in its own thread: Django's async ORM would serialize the four queries
    # through its single sync_to_async executor thread, making the endpoint latency the SUM of
    # the four queries instead of their max. Threads keep their own DB connection; drop stale
    # ones so the executor threads do not accumulate dead connections.
    try:
        return fetcher(query_term, user_point)
    finally:
        for conn in connections.all():
            conn.close_if_unusable_or_obsolete()


async def get_aggregated_response(query, latitude: float | None, longitude: float | None
                                  ) -> list[AutocompleteResult]:
    if not query or len(query) > 200 or len(query) < 3 or not query[0].isalnum():
        return []

    query_term = normalize_city_name(query)
    user_point = None
    if latitude is not None and longitude is not None:
        user_point = Point(longitude, latitude, srid=4326)

    all_scored = await asyncio.gather(*(
        asyncio.to_thread(_fetch_in_thread, fetcher, query_term, user_point)
        for fetcher in (get_city_response, get_website_by_name_response,
                        get_parish_by_name_response, get_church_by_name_response)))

    scored = [scored_result for source in all_scored for scored_result in source]
    scored.sort(key=lambda t: t[0], reverse=True)

    seen_urls = set()
    unique_results = []
    for _score, result in scored:
        if result.url not in seen_urls:
            seen_urls.add(result.url)
            unique_results.append(result)

    return unique_results[:MAX_AUTOCOMPLETE_RESULTS]
