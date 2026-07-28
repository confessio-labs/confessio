"""Build recall-oriented autocomplete candidate pools with raw score components.

For every unique (query, latitude, longitude) among the resolved hits, fetch up to POOL_SIZE
candidates per source with the LIVE retrieval predicates and scoring annotations (imported
from autocomplete_service, so predicates/components cannot drift from prod). Each pool row
carries the RAW components (s_prefix, s_substr, s_sim, s_word, s_pop, distance_m) so the grid
search can re-weight and change the geo decay without re-querying. `s_pop` holds the commune
population on municipality rows and the website traffic on the other three.
"""
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from django.contrib.gis.db.models import Collect
from django.contrib.gis.db.models.functions import Centroid
from django.contrib.gis.geos import Point
from django.db import connections
from django.db.models import F, Q
from django.db.models.functions import Greatest
from django.urls import reverse

from front.services.search.autocomplete_service import (annotate_search_score,
                                                        city_pop_expression,
                                                        hits_pop_expression,
                                                        long_name_predicate)
from registry.models import City, Parish, Church, Website
from registry.utils.city_name_utils import normalize_city_name

POOL_SIZE = 200


def _dist_m(value) -> float | None:
    if value is None:
        return None
    return float(value.m) if hasattr(value, 'm') else float(value)


def _rows(qs, url_of, row_type) -> list[dict]:
    best = Greatest(F('s_prefix'), F('s_substr'), F('s_sim'), F('s_word'))
    rows = []
    for obj in qs.annotate(best=best).order_by('-best')[:POOL_SIZE]:
        rows.append({
            'type': row_type, 'url': url_of(obj),
            's_prefix': obj.s_prefix, 's_substr': obj.s_substr,
            's_sim': obj.s_sim, 's_word': obj.s_word, 's_pop': obj.s_pop,
            'distance_m': _dist_m(obj.distance),
        })
    return rows


def build_pools_for_key(key: tuple) -> dict[str, list[dict]]:
    query, latitude, longitude = key
    if not query or len(query) > 200 or len(query) < 3 or not query[0].isalnum():
        return {'municipality': [], 'parish': [], 'website': [], 'church': []}
    q = normalize_city_name(query)
    point = Point(longitude, latitude, srid=4326)

    cities = City.objects.filter(
        Q(name_norm__trigram_similar=q) | Q(name_norm__startswith=q), slug__isnull=False)
    # No type_boost and no pop_weight here on purpose: _rows ranks by `best`, the max of the four
    # STRING signals, which no weight can change. That is what makes offline re-weighting of the
    # cached rows valid — the pool is a retrieval set, not a ranking.
    cities = annotate_search_score(
        cities, q, point, 'location', 0.0, pop_expression=city_pop_expression())
    city_rows = _rows(
        cities, lambda c: reverse('city_view', kwargs={'city_slug': c.slug}), 'municipality')

    predicate = long_name_predicate(q)

    parishes = Parish.objects.select_related('website') \
        .filter(website__is_active=True).filter(predicate) \
        .annotate(centroid=Centroid(Collect('churches__location')))
    parish_rows = _rows(
        annotate_search_score(parishes, q, point, 'centroid', 0.0,
                              pop_expression=hits_pop_expression('website__nb_recent_hits')),
        lambda p: reverse('website_view', kwargs={'website_uuid': p.website.uuid}), 'parish')

    websites = Website.objects.filter(is_active=True).filter(predicate) \
        .annotate(centroid=Centroid(Collect('parishes__churches__location')))
    website_rows = _rows(
        annotate_search_score(websites, q, point, 'centroid', 0.0,
                              pop_expression=hits_pop_expression('nb_recent_hits')),
        lambda w: reverse('website_view', kwargs={'website_uuid': w.uuid}), 'parish')

    churches = Church.objects.select_related('parish__website') \
        .filter(is_active=True, parish__website__is_active=True).filter(predicate)
    church_rows = _rows(
        annotate_search_score(
            churches, q, point, 'location', 0.0,
            pop_expression=hits_pop_expression('parish__website__nb_recent_hits')),
        lambda c: reverse('website_view', kwargs={'website_uuid': c.parish.website.uuid}),
        'church')

    return {'municipality': city_rows, 'parish': parish_rows,
            'website': website_rows, 'church': church_rows}


def build_pools(keys: list[tuple], already_built: dict[tuple, dict],
                on_progress: Callable[[dict[tuple, dict], int, int], None],
                ) -> dict[tuple, dict[str, list[dict]]]:
    """Build pools for the keys missing from already_built, 8 queries in parallel.

    Calls on_progress(pools, done, total) periodically so the caller can checkpoint.
    """
    pools = dict(already_built)
    todo = [k for k in keys if k not in pools]

    def work(key):
        try:
            return key, build_pools_for_key(key)
        finally:
            for conn in connections.all():
                conn.close_if_unusable_or_obsolete()

    with ThreadPoolExecutor(max_workers=8) as executor:
        for i, (key, result) in enumerate(executor.map(work, todo)):
            pools[key] = result
            if (i + 1) % 200 == 0:
                on_progress(pools, i + 1, len(todo))
    return pools


def report_pool_recall(hits, pools: dict[tuple, dict]) -> list[str]:
    """How often the picked item is in its candidate pool at all (retrieval upper bound)."""
    lines = []
    for item_type in ('municipality', 'parish', 'church'):
        subset = [h for h in hits if h.item_type == item_type]
        if not subset:
            continue
        found = sum(
            1 for h in subset
            if any(r['url'] == h.target_url
                   for rows in pools.get(h.key, {}).values() for r in rows))
        lines.append(f'pool recall {item_type:14s}: {found}/{len(subset)}'
                     f' = {found / len(subset):.3f}')
    return lines
