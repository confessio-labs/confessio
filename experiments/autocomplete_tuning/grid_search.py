"""Staged coordinate grid search over the shared score weights, on cached pools.

Objective: overall MRR on the train split (hits are 81% municipality, so overall MRR is the
traffic-weighted metric), subject to hard gates checked at the end against the baseline replay:
  - municipality top-1 >= baseline municipality top-1 (city ranking must not regress)
  - overall MRR >= baseline overall MRR
  - parish top-1 > baseline parish top-1 (the defect being fixed)
Validation numbers (post-split hits) are reported alongside to expose overfitting.
"""
from dataclasses import replace

from common import SPLIT_DATE, cache_load, django_setup, load_and_resolve_hits
from metrics import render, summarize
from pools import POOLS_CACHE
from replay import outcomes_from_ranked
from scoring import Config, rank_pools

STAGES = [
    # (stage name, [(field, values)]) — full product within a stage, best carried forward.
    ('geo', [('geo_w', [0.0, 4.0, 8.0, 12.0, 18.0, 24.0]),
             ('half_life_km', [25.0, 50.0, 100.0, 200.0, 400.0]),
             ('geo_shape', ['inv', 'exp'])]),
    ('string', [('sim_w', [0.0, 5.0, 10.0, 20.0, 30.0]),
                ('word_w', [0.0, 10.0, 20.0, 30.0, 40.0]),
                ('substr_w', [0.0, 5.0, 10.0, 20.0])]),
    ('boosts', [('boost_municipality', [0.0, 2.0, 4.0, 8.0]),
                ('boost_parish', [0.0, 2.0, 4.0]),
                ('boost_church', [0.0, 2.0, 4.0])]),
    ('pop', [('pop_w', [10.0, 20.0, 30.0])]),
]


def evaluate(config: Config, hits, pools) -> dict[str, dict]:
    keys = {h.key for h in hits}
    ranked = {key: rank_pools(pools[key], config) for key in keys if key in pools}
    return summarize(outcomes_from_ranked(hits, ranked))


def product(dimensions):
    configs = [{}]
    for field, values in dimensions:
        configs = [{**c, field: v} for c in configs for v in values]
    return configs


def refine(value: float, step_ratio: float = 0.5) -> list[float]:
    if value == 0.0:
        return [0.0, 1.0, 2.0]
    return sorted({value * (1 - step_ratio / 2), value, value * (1 + step_ratio / 2)})


def main():
    django_setup()
    hits, _skips = load_and_resolve_hits()
    pools = cache_load(POOLS_CACHE)
    assert pools is not None, 'run pools.py first'
    train = [h for h in hits if h.created_at <= SPLIT_DATE]
    val = [h for h in hits if h.created_at > SPLIT_DATE]
    print(f'{len(train)} train hits, {len(val)} validation hits\n')

    best = Config()
    best_mrr = evaluate(best, train, pools)['overall']['mrr']
    print(f'start {best} -> train MRR {best_mrr:.4f}\n')

    for stage_name, dimensions in STAGES:
        results = []
        for overrides in product(dimensions):
            config = replace(best, **overrides)
            rows = evaluate(config, train, pools)
            results.append((rows['overall']['mrr'], overrides, rows))
        results.sort(key=lambda t: t[0], reverse=True)
        top_mrr, top_overrides, top_rows = results[0]
        print(f'[{stage_name}] best {top_overrides} -> train MRR {top_mrr:.4f} '
              f'(muni top-1 {top_rows["municipality"]["top1"]:.3f}, '
              f'parish top-1 {top_rows["parish"]["top1"]:.3f}, '
              f'church top-1 {top_rows["church"]["top1"]:.3f})')
        for mrr, overrides, _rows in results[1:4]:
            print(f'    runner-up {overrides} -> {mrr:.4f}')
        if top_mrr >= best_mrr:
            best, best_mrr = replace(best, **top_overrides), top_mrr
        print()

    # coordinate-wise refinement around the winner on the numeric weights
    for field in ('geo_w', 'half_life_km', 'sim_w', 'word_w', 'substr_w',
                  'boost_municipality', 'boost_parish', 'boost_church', 'pop_w'):
        for value in refine(getattr(best, field)):
            config = replace(best, **{field: value})
            mrr = evaluate(config, train, pools)['overall']['mrr']
            if mrr > best_mrr:
                best, best_mrr = replace(best, **{field: value}), mrr
    print(f'refined winner: {best} -> train MRR {best_mrr:.4f}\n')

    baseline_ranked = cache_load('baseline.pkl')
    assert baseline_ranked is not None, 'run replay.py --mode baseline first'
    base_all = summarize(outcomes_from_ranked(hits, baseline_ranked))
    winner_all = evaluate(best, hits, pools)
    runs = {
        'baseline / all': base_all,
        'winner / all': winner_all,
        'baseline / validation': summarize(outcomes_from_ranked(val, baseline_ranked)),
        'winner / validation': evaluate(best, val, pools),
        'winner / train': evaluate(best, train, pools),
    }
    print(render(runs))
    print('\ngates (on all hits):')
    print(f"  municipality top-1 {winner_all['municipality']['top1']:.3f} >= "
          f"baseline {base_all['municipality']['top1']:.3f}: "
          f"{winner_all['municipality']['top1'] >= base_all['municipality']['top1']}")
    print(f"  overall MRR {winner_all['overall']['mrr']:.3f} >= "
          f"baseline {base_all['overall']['mrr']:.3f}: "
          f"{winner_all['overall']['mrr'] >= base_all['overall']['mrr']}")
    print(f"  parish top-1 {winner_all['parish']['top1']:.3f} > "
          f"baseline {base_all['parish']['top1']:.3f}: "
          f"{winner_all['parish']['top1'] > base_all['parish']['top1']}")


if __name__ == '__main__':
    main()
