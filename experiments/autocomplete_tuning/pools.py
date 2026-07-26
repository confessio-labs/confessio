"""Build recall-oriented candidate pools with raw score components, per unique replay context.

For every unique (query, latitude, longitude) among the resolved hits, fetch up to POOL_SIZE
candidates per type with the CANDIDATE retrieval predicates:
  - city:   name_norm startswith OR trigram_similar (unchanged from prod)
  - parish/website/church: normalized-name contains OR trigram_word_similar (new)
Each pool row carries the RAW components (s_prefix, s_substr, s_sim, s_word, s_pop, distance_m)
so the grid search can re-weight and change the geo decay without re-querying.
"""
import time
from concurrent.futures import ThreadPoolExecutor

from common import ResolvedHit, cache_load, cache_save, django_setup

POOL_SIZE = 200
POOLS_CACHE = 'pools.pkl'
MAX_LN_POPULATION = 14.73

# Runtime equivalent of the future name_norm generated column (STABLE unaccent is fine here).


def _norm_expression():
    from django.contrib.postgres.lookups import Unaccent
    from django.db.models import Value
    from django.db.models.functions import Lower, Replace
    return Replace(Replace(Lower(Unaccent('name')), Value('-'), Value(' ')),
                   Value("'"), Value(' '))


def _annotate_components(qs, query_term, point, geo_field, norm_field, pop_expression=None):
    from django.contrib.gis.db.models.functions import Distance
    from django.contrib.postgres.search import TrigramSimilarity, TrigramWordSimilarity
    from django.db.models import Case, FloatField, Value, When
    return qs.annotate(
        s_prefix=Case(When(**{f'{norm_field}__startswith': query_term}, then=Value(1.0)),
                      default=Value(0.0), output_field=FloatField()),
        s_substr=Case(When(**{f'{norm_field}__contains': query_term}, then=Value(1.0)),
                      default=Value(0.0), output_field=FloatField()),
        s_sim=TrigramSimilarity(norm_field, query_term),
        s_word=TrigramWordSimilarity(query_term, norm_field),
        s_pop=pop_expression if pop_expression is not None
        else Value(0.0, output_field=FloatField()),
        dist=Distance(geo_field, point),
    )


def _dist_m(value) -> float | None:
    if value is None:
        return None
    return float(value.m) if hasattr(value, 'm') else float(value)


def _rows(qs, url_of, row_type) -> list[dict]:
    from django.db.models import F
    from django.db.models.functions import Greatest
    best = Greatest(F('s_prefix'), F('s_substr'), F('s_sim'), F('s_word'))
    out = []
    for obj in qs.annotate(best=best).order_by('-best')[:POOL_SIZE]:
        out.append({
            'type': row_type, 'url': url_of(obj),
            's_prefix': obj.s_prefix, 's_substr': obj.s_substr,
            's_sim': obj.s_sim, 's_word': obj.s_word, 's_pop': obj.s_pop,
            'distance_m': _dist_m(obj.dist),
        })
    return out


def build_pools_for_key(key: tuple) -> dict[str, list[dict]]:
    from django.contrib.gis.db.models import Collect
    from django.contrib.gis.db.models.functions import Centroid
    from django.contrib.gis.geos import Point
    from django.db.models import F, FloatField, Q, Value
    from django.db.models.functions import Greatest, Ln
    from django.db.models import ExpressionWrapper
    from django.urls import reverse
    from registry.models import City, Parish, Church, Website
    from registry.utils.city_name_utils import normalize_city_name

    query, latitude, longitude = key
    if not query or len(query) > 200 or len(query) < 3 or not query[0].isalnum():
        return {'municipality': [], 'parish': [], 'website': [], 'church': []}
    q = normalize_city_name(query)
    point = Point(longitude, latitude, srid=4326)

    cities = City.objects.filter(
        Q(name_norm__startswith=q) | Q(name_norm__trigram_similar=q),
        slug__isnull=False,
    )
    cities = _annotate_components(
        cities, q, point, 'location', 'name_norm',
        pop_expression=ExpressionWrapper(
            Ln(Greatest(F('population'), Value(1))) / Value(MAX_LN_POPULATION),
            output_field=FloatField()))
    city_rows = _rows(
        cities, lambda c: reverse('city_view', kwargs={'city_slug': c.slug}), 'municipality')

    long_predicate = Q(norm_name__contains=q) | Q(norm_name__trigram_word_similar=q)

    parishes = Parish.objects.select_related('website') \
        .filter(website__is_active=True).annotate(norm_name=_norm_expression()) \
        .filter(long_predicate).annotate(centroid=Centroid(Collect('churches__location')))
    parish_rows = _rows(
        _annotate_components(parishes, q, point, 'centroid', 'norm_name'),
        lambda p: reverse('website_view', kwargs={'website_uuid': p.website.uuid}), 'parish')

    websites = Website.objects.filter(is_active=True).annotate(norm_name=_norm_expression()) \
        .filter(long_predicate) \
        .annotate(centroid=Centroid(Collect('parishes__churches__location')))
    website_rows = _rows(
        _annotate_components(websites, q, point, 'centroid', 'norm_name'),
        lambda w: reverse('website_view', kwargs={'website_uuid': w.uuid}), 'parish')

    churches = Church.objects.select_related('parish__website') \
        .filter(is_active=True, parish__website__is_active=True) \
        .annotate(norm_name=_norm_expression()).filter(long_predicate)
    church_rows = _rows(
        _annotate_components(churches, q, point, 'location', 'norm_name'),
        lambda c: reverse('website_view', kwargs={'website_uuid': c.parish.website.uuid}),
        'church')

    return {'municipality': city_rows, 'parish': parish_rows,
            'website': website_rows, 'church': church_rows}


def build_pools(hits: list[ResolvedHit]) -> dict[tuple, dict[str, list[dict]]]:
    from django.db import connections
    pools = cache_load(POOLS_CACHE) or {}
    keys = [k for k in {h.key for h in hits} if k not in pools]
    print(f'{len(pools)} pools cached, {len(keys)} to build')
    start = time.time()

    def work(key):
        try:
            return key, build_pools_for_key(key)
        finally:
            for conn in connections.all():
                conn.close_if_unusable_or_obsolete()

    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, (key, result) in enumerate(pool.map(work, keys)):
            pools[key] = result
            if (i + 1) % 200 == 0:
                print(f'  {i + 1}/{len(keys)} pools ({time.time() - start:.0f}s)')
                cache_save(POOLS_CACHE, pools)
    cache_save(POOLS_CACHE, pools)
    return pools


if __name__ == '__main__':
    django_setup()
    from common import load_and_resolve_hits
    resolved, skips = load_and_resolve_hits()
    print(f'resolved {len(resolved)} hits, skipped {sum(skips.values())}: {skips}')
    build_pools(resolved)
    print('pools built')
