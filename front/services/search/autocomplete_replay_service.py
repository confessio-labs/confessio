"""Resolve recorded autocomplete hits and replay them through the live service.

Feeds the `autocomplete_tuning` management command.
"""
import asyncio
from datetime import datetime
from typing import Callable

from django.urls import reverse

from front.models import AutocompleteHit
from front.services.search.autocomplete_hit_service import AutocompleteHitResolver
from front.services.search.autocomplete_service import get_aggregated_response
from front.utils.autocomplete_metrics_utils import ResolvedHit
from registry.models import City
from registry.utils.city_name_utils import normalize_city_name


def load_and_resolve_hits(max_created_at: datetime | None = None
                          ) -> tuple[list[ResolvedHit], dict[str, int]]:
    """One resolution path per type; unmatched hits are skip-counted, never guessed.

    `max_created_at` drops the hits recorded inside the nb_recent_hits window — see the
    --hit-cutoff-days option of the autocomplete_tuning command.
    """
    cities_by_name: dict[str, list] = {}
    for c in City.objects.all().only('zipcode', 'name_norm', 'slug', 'population'):
        cities_by_name.setdefault(c.name_norm, []).append(c)
    website_resolver = AutocompleteHitResolver()

    resolved, skips = [], {}

    def skip(reason: str):
        skips[reason] = skips.get(reason, 0) + 1

    for hit in AutocompleteHit.objects.all().order_by('created_at'):
        # Such a hit caused part of the popularity that would rank it: the pick navigates to
        # /paroisse/<uuid>, which update_popularity_of_websites counts. Scoring it with the
        # current snapshot leaks the label into s_popularity.
        if max_created_at is not None and hit.created_at >= max_created_at:
            skip('inside-popularity-window')
            continue
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
        else:
            website, reason = website_resolver.resolve_website(hit.item_type, hit.item_uuid)
            if website is None:
                skip(reason)
                continue
            target_url = reverse('website_view', kwargs={'website_uuid': website.uuid})

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
                results = await get_aggregated_response(query, latitude, longitude)
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
