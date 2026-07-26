"""Replay recorded autocomplete hits through baseline / candidate / refactored service.

  python experiments/autocomplete_tuning/replay.py --mode baseline
  python experiments/autocomplete_tuning/replay.py --mode candidate --geo-weight 12 ...
  python experiments/autocomplete_tuning/replay.py --mode service    # post-refactor fidelity

baseline/service run the LIVE get_aggregated_response (cached per mode); candidate re-ranks
the cached pools in pure Python. All modes print top-1/top-3/MRR/recall@15, overall + per type.
"""
import argparse
import asyncio
import time

from common import (SPLIT_DATE, ResolvedHit, cache_load, cache_save, django_setup,
                    load_and_resolve_hits)
from metrics import HitOutcome, render, summarize


async def _run_live(keys: list[tuple], cache_name: str) -> dict[tuple, list[str]]:
    from front.services.search.autocomplete_service import get_aggregated_response
    ranked = cache_load(cache_name) or {}
    todo = [k for k in keys if k not in ranked]
    print(f'{len(ranked)} live replays cached, {len(todo)} to run')
    sem = asyncio.Semaphore(8)
    start = time.time()

    async def one(key):
        query, latitude, longitude = key
        async with sem:
            results = await get_aggregated_response(query, latitude, longitude)
        return key, [r.url for r in results]

    for i in range(0, len(todo), 200):
        batch = todo[i:i + 200]
        for key, urls in await asyncio.gather(*(one(k) for k in batch)):
            ranked[key] = urls
        cache_save(cache_name, ranked)
        print(f'  {min(i + 200, len(todo))}/{len(todo)} ({time.time() - start:.0f}s)')
    return ranked


def outcomes_from_ranked(hits: list[ResolvedHit],
                         ranked: dict[tuple, list[str]]) -> list[HitOutcome]:
    out = []
    for hit in hits:
        urls = ranked.get(hit.key, [])
        rank = urls.index(hit.target_url) + 1 if hit.target_url in urls else None
        out.append(HitOutcome(item_type=hit.item_type, rank=rank,
                              in_train=hit.created_at <= SPLIT_DATE))
    return out


def report_agreement(hits: list[ResolvedHit], ranked: dict[tuple, list[str]]) -> None:
    """Sanity check for baseline: replayed rank vs the rank recorded at pick time."""
    same = close = matched = 0
    for hit in hits:
        urls = ranked.get(hit.key, [])
        if hit.target_url in urls:
            matched += 1
            rank0 = urls.index(hit.target_url)
            same += rank0 == hit.recorded_rank
            close += abs(rank0 - hit.recorded_rank) <= 1
    print(f'agreement with recorded ranks: exact {same / matched:.1%},'
          f' ±1 {close / matched:.1%} (on {matched} matched hits)\n')


def report_predicate_recall(hits: list[ResolvedHit], pools: dict) -> None:
    """How often the picked item is in its candidate pool at all (retrieval upper bound)."""
    for item_type in ('municipality', 'parish', 'church'):
        subset = [h for h in hits if h.item_type == item_type]
        found = sum(
            1 for h in subset
            if any(r['url'] == h.target_url
                   for rows in pools.get(h.key, {}).values() for r in rows))
        print(f'pool recall {item_type:14s}: {found}/{len(subset)} = {found / len(subset):.3f}')
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['baseline', 'candidate', 'service'],
                        required=True)
    parser.add_argument('--prefix-weight', type=float, default=50.0)
    parser.add_argument('--substr-weight', type=float, default=0.0)
    parser.add_argument('--sim-weight', type=float, default=10.0)
    parser.add_argument('--word-weight', type=float, default=0.0)
    parser.add_argument('--geo-weight', type=float, default=12.0)
    parser.add_argument('--pop-weight', type=float, default=20.0)
    parser.add_argument('--geo-half-life-km', type=float, default=50.0)
    parser.add_argument('--geo-shape', choices=['inv', 'exp'], default='inv')
    parser.add_argument('--boost-municipality', type=float, default=0.0)
    parser.add_argument('--boost-parish', type=float, default=0.0)
    parser.add_argument('--boost-church', type=float, default=0.0)
    args = parser.parse_args()

    django_setup()
    hits, skips = load_and_resolve_hits()
    print(f'resolved {len(hits)} hits\n')

    if args.mode in ('baseline', 'service'):
        ranked = asyncio.run(_run_live([h.key for h in hits], f'{args.mode}.pkl'))
        outcomes = outcomes_from_ranked(hits, ranked)
        if args.mode == 'baseline':
            report_agreement(hits, ranked)
    else:
        from pools import POOLS_CACHE
        from scoring import Config, rank_pools
        pools = cache_load(POOLS_CACHE)
        assert pools is not None, 'run pools.py first'
        report_predicate_recall(hits, pools)
        config = Config(
            prefix_w=args.prefix_weight, substr_w=args.substr_weight, sim_w=args.sim_weight,
            word_w=args.word_weight, geo_w=args.geo_weight, pop_w=args.pop_weight,
            half_life_km=args.geo_half_life_km, geo_shape=args.geo_shape,
            boost_municipality=args.boost_municipality, boost_parish=args.boost_parish,
            boost_church=args.boost_church)
        keys = {h.key for h in hits}
        ranked = {key: rank_pools(pools[key], config) for key in keys if key in pools}
        outcomes = outcomes_from_ranked(hits, ranked)

    print(render({args.mode: summarize(outcomes)}, skips))


if __name__ == '__main__':
    main()
