"""Resolve recorded autocomplete hits and replay them through the live service.

Feeds the `autocomplete_tuning` management command. Hits come from
front.models.AutocompleteHit (models are a permitted cross-module import); the live replay
goes through front.public_service.
"""
import asyncio
from typing import Callable

from django.urls import reverse

from front.models import AutocompleteHit
from front.public_service import front_get_autocomplete_response
from registry.models import City, Parish, Church, Website
from registry.utils.autocomplete_metrics_utils import ResolvedHit
from registry.utils.city_name_utils import normalize_city_name


def load_and_resolve_hits() -> tuple[list[ResolvedHit], dict[str, int]]:
    """One resolution path per type; unmatched hits are skip-counted, never guessed."""
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


def replay_live(keys: list[tuple], already_ranked: dict[tuple, list[str]],
                on_batch: Callable[[dict[tuple, list[str]], int, int], None],
                ) -> dict[tuple, list[str]]:
    """Replay each (query, lat, lng) through the LIVE autocomplete service.

    Skips keys present in already_ranked; calls on_batch(ranked, done, total) after each
    batch so the caller can checkpoint its cache.
    """
    ranked = dict(already_ranked)
    todo = [k for k in keys if k not in ranked]

    async def run():
        sem = asyncio.Semaphore(8)

        async def one(key):
            query, latitude, longitude = key
            async with sem:
                results = await front_get_autocomplete_response(query, latitude, longitude)
            return key, [r.url for r in results]

        for i in range(0, len(todo), 200):
            batch = todo[i:i + 200]
            for key, urls in await asyncio.gather(*(one(k) for k in batch)):
                ranked[key] = urls
            on_batch(ranked, min(i + 200, len(todo)), len(todo))

    asyncio.run(run())
    return ranked


def report_agreement(hits: list[ResolvedHit], ranked: dict[tuple, list[str]]) -> str:
    """Sanity check: replayed rank vs the rank recorded at pick time."""
    same = close = matched = 0
    for hit in hits:
        urls = ranked.get(hit.key, [])
        if hit.target_url in urls:
            matched += 1
            rank0 = urls.index(hit.target_url)
            same += rank0 == hit.recorded_rank
            close += abs(rank0 - hit.recorded_rank) <= 1
    if not matched:
        return 'agreement with recorded ranks: no matched hits'
    return (f'agreement with recorded ranks: exact {same / matched:.1%},'
            f' ±1 {close / matched:.1%} (on {matched} matched hits)')
