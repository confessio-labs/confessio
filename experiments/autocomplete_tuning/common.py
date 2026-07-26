"""Shared plumbing for the autocomplete tuning harness (throwaway, not committed).

Resolves each recorded AutocompleteHit to the URL the pick leads to, so a replayed ranking can
be checked for it. One resolution path per type, unmatched hits are skip-counted and reported.
"""
import os
import pickle
import sys
from dataclasses import dataclass
from datetime import datetime

EXPERIMENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(EXPERIMENT_DIR))
CACHE_DIR = os.path.join(EXPERIMENT_DIR, 'cache')

# Train/validation time split for the grid search (tune on <=, validate on >).
SPLIT_DATE = datetime.fromisoformat('2026-06-15T23:59:59+00:00')


def django_setup():
    sys.path.insert(0, REPO_DIR)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    import django
    django.setup()


def cache_path(name: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, name)


def cache_load(name: str):
    path = cache_path(name)
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return pickle.load(f)
    return None


def cache_save(name: str, obj) -> None:
    with open(cache_path(name), 'wb') as f:
        pickle.dump(obj, f)


@dataclass
class ResolvedHit:
    query: str
    latitude: float
    longitude: float
    item_type: str        # 'municipality' | 'parish' | 'church' ('parish' covers websites too)
    # URL of the picked item; ranking match is URL-based (post-dedupe a result list has at most
    # one row per URL)
    target_url: str
    recorded_rank: int    # 0-based rank the user picked under the ranking live at the time
    created_at: datetime

    @property
    def key(self) -> tuple:
        return self.query, round(self.latitude, 6), round(self.longitude, 6)


def load_and_resolve_hits() -> tuple[list[ResolvedHit], dict[str, int]]:
    from django.urls import reverse
    from front.models import AutocompleteHit
    from registry.models import City, Parish, Church, Website
    from registry.utils.city_name_utils import normalize_city_name

    cities_by_name: dict[str, list] = {}
    for c in City.objects.all().only('zipcode', 'name_norm', 'slug', 'population'):
        cities_by_name.setdefault(c.name_norm, []).append(c)
    parish_by_uuid = {str(p.uuid): p for p in Parish.objects.select_related('website')}
    website_by_uuid = {str(w.uuid): w for w in Website.objects.all()}
    church_by_uuid = {str(c.uuid): c
                      for c in Church.objects.select_related('parish__website')}

    resolved, skips = [], {}

    def skip(reason: str):
        skips[reason] = skips.get(reason, 0) + 1

    for hit in AutocompleteHit.objects.all().order_by('created_at'):
        if hit.latitude is None or hit.longitude is None:
            skip('no-user-location')
            continue
        target_url = None
        if hit.item_type == 'municipality':
            # Most municipality hits predate the City table (item_uuid is NULL, context is the
            # zipcode — often empty or a secondary zipcode for big multi-zipcode communes like
            # Paris/Lyon/Aix). Match by normalized name; zipcode only disambiguates homonyms,
            # population breaks the remaining ties (counted).
            candidates = cities_by_name.get(normalize_city_name(hit.item_name or ''), [])
            if not candidates:
                skip('city-unmatched')
                continue
            if len(candidates) > 1:
                by_zip = [c for c in candidates if c.zipcode == hit.item_context]
                candidates = by_zip or candidates
            if len(candidates) > 1:
                skip('city-ambiguous-took-biggest')
                candidates.sort(key=lambda c: c.population, reverse=True)
            if not candidates[0].slug:
                skip('city-no-slug')
                continue
            target_url = reverse('city_view', kwargs={'city_slug': candidates[0].slug})
        elif hit.item_type == 'parish':
            obj = parish_by_uuid.get(hit.item_uuid)
            website = obj.website if obj else website_by_uuid.get(hit.item_uuid)
            if website is None:
                skip('parish-uuid-not-found')
                continue
            if not website.is_active:
                skip('website-now-inactive')
                continue
            target_url = reverse('website_view', kwargs={'website_uuid': website.uuid})
        elif hit.item_type == 'church':
            church = church_by_uuid.get(hit.item_uuid)
            if church is None or church.parish.website is None:
                skip('church-uuid-not-found')
                continue
            if not church.parish.website.is_active:
                skip('website-now-inactive')
                continue
            target_url = reverse('website_view',
                                 kwargs={'website_uuid': church.parish.website.uuid})
        else:
            skip(f'unknown-type-{hit.item_type}')
            continue

        resolved.append(ResolvedHit(
            query=hit.query, latitude=hit.latitude, longitude=hit.longitude,
            item_type=hit.item_type, target_url=target_url,
            recorded_rank=hit.rank, created_at=hit.created_at,
        ))

    return resolved, skips
