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
from django.db.models.functions import Coalesce, Exp, Greatest, Ln
from django.urls import reverse

from front.utils.department_utils import get_departments_context
from registry.models import City, Parish, Church, Website
from registry.utils.city_name_utils import normalize_city_name

MAX_AUTOCOMPLETE_RESULTS = 15

# Weights of the shared ranking score, computed in SQL for all four sources so their results are
# directly comparable. Grid-searched on 4143 recorded autocomplete hits (front_autocompletehit,
# Apr-Jul 2026) replayed through the retrieval, with a time-split validation (tune <= Jun 15,
# validate after). Baseline (previous two-scorer ranking) vs this score, top-1/MRR on all hits:
# overall .756/.824 -> .758/.826, municipality .867/.902 -> .865/.899, parish .215/.450 ->
# .248/.502, church .355/.525 -> .355/.506; on the validation split parish top-1 goes
# .297 -> .441 and municipality .865 -> .877.
PREFIX_WEIGHT = 50.0
# Exact-substring bonus: parish and church names are long ('Paroisse Saint-Leger en
# Saint-Maixentais'), where trigram similarity is mechanically low for a short query.
SUBSTRING_WEIGHT = 10.0
SIMILARITY_WEIGHT = 6.0
# word_similarity() scores the query against the best-matching word span, so it is the string
# signal that works on long names ('saint maixentais' scores 1.0 vs 0.49 plain similarity).
WORD_SIMILARITY_WEIGHT = 15.0
GEO_WEIGHT = 18.0
POPULATION_WEIGHT = 20.0
# ln(2_500_000), a bit above the most populated commune, so that s_pop stays in [0, 1]
MAX_LN_POPULATION = 14.73
# Geo proximity is an ADDITIVE bonus with a fast exponential decay: score halves every 30 km.
# The previous ranking MULTIPLIED name similarity by 50km/(50km+d), which buried far exact
# matches: 34% of recorded picks are >50 km away and 26% >200 km (trips, home towns), and
# rank>0 picks were measurably farther than rank-0 picks (median 30.6 km vs 19.4 km). Additive
# geo can never bury an exact name match; it acts as a local tie-breaker.
GEO_HALF_LIFE_METERS = 30000.0
# Per-type additive boosts, same grid search. Municipalities need none (prefix + population
# already carry them); parishes and churches were systematically outranked before (parish picks
# landed at rank 0 only 40% of the time, vs 88% for municipalities).
TYPE_BOOSTS = {'municipality': 0.0, 'parish': 5.0, 'church': 4.0}


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


def annotate_search_score(qs, query_term: str, user_point: Point | None, geo_field: str,
                          type_boost: float, pop_expression=None):
    """Annotate the shared autocomplete ranking score, computed entirely in SQL.

    All four sources get the exact same formula so their `final_score` values are comparable
    and the merge is a plain sort. `geo_field` names a geometry column or annotation
    ('location', or a pre-annotated 'centroid'); `pop_expression` is only set for City today.
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
        s_pop=pop_expression if pop_expression is not None
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

    return qs.annotate(
        final_score=ExpressionWrapper(
            F('s_prefix') * Value(PREFIX_WEIGHT)
            + F('s_substr') * Value(SUBSTRING_WEIGHT)
            + F('s_sim') * Value(SIMILARITY_WEIGHT)
            + F('s_word') * Value(WORD_SIMILARITY_WEIGHT)
            + F('s_geo') * Value(GEO_WEIGHT)
            + F('s_pop') * Value(POPULATION_WEIGHT)
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
        pop_expression=ExpressionWrapper(
            Ln(Greatest(F('population'), Value(1))) / Value(MAX_LN_POPULATION),
            output_field=FloatField(),
        ),
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
        query_term, user_point, 'centroid', TYPE_BOOSTS['parish'])
    hydration = Parish.objects.select_related('website').prefetch_related('churches') \
        .only('name', 'website__uuid')

    return _scored_then_hydrated(scoring, hydration, AutocompleteResult.from_parish)


def get_website_by_name_response(query_term: str,
                                 user_point: Point | None) -> ScoredResults:
    scoring = annotate_search_score(
        Website.objects.filter(is_active=True).filter(long_name_predicate(query_term))
        .annotate(centroid=Centroid(Collect('parishes__churches__location'))),
        query_term, user_point, 'centroid', TYPE_BOOSTS['parish'])
    hydration = Website.objects.prefetch_related('parishes__churches').only('name', 'uuid')

    return _scored_then_hydrated(scoring, hydration, AutocompleteResult.from_website)


def get_church_by_name_response(query_term: str,
                                user_point: Point | None) -> ScoredResults:
    scoring = annotate_search_score(
        Church.objects.filter(is_active=True, parish__website__is_active=True)
        .filter(long_name_predicate(query_term)),
        query_term, user_point, 'location', TYPE_BOOSTS['church'])
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
