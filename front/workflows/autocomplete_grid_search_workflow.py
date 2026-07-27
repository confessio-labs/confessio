"""Staged coordinate grid search over the shared autocomplete score weights.

Pure pipeline (rule 2: no model/service imports): operates on resolved hits and cached pools
passed in by the `autocomplete_tuning` command. Objective: overall MRR on the train split
(hits are ~80% municipality, so overall MRR is the traffic-weighted metric), subject to hard
gates checked at the end against the live-replay summary:
  - municipality top-1 >= replay municipality top-1 (city ranking must not regress)
  - overall MRR >= replay overall MRR
  - parish top-1 > replay parish top-1
Validation numbers (post-split hits) are reported alongside to expose overfitting.
"""
from dataclasses import replace
from typing import Callable

from front.utils.autocomplete_metrics_utils import (ResolvedHit, outcomes_from_ranked,
                                                    render, summarize)
from front.utils.autocomplete_scoring_utils import ScoringConfig, rank_pools

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
    ('gate', [('gate_threshold', [0.0, 0.3, 0.45, 0.5, 0.6])]),
]
REFINED_FIELDS = ('geo_w', 'half_life_km', 'sim_w', 'word_w', 'substr_w',
                  'boost_municipality', 'boost_parish', 'boost_church', 'pop_w',
                  'gate_threshold')


def evaluate(config: ScoringConfig, hits: list[ResolvedHit], pools: dict) -> dict[str, dict]:
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


def run_grid_search(start: ScoringConfig, train: list[ResolvedHit], val: list[ResolvedHit],
                    all_hits: list[ResolvedHit], pools: dict,
                    replay_summary: dict[str, dict], log: Callable[[str], None],
                    ) -> ScoringConfig:
    """Returns the winning config; prints stages, final tables and gates through `log`."""
    best = start
    best_mrr = evaluate(best, train, pools)['overall']['mrr']
    log(f'start {best} -> train MRR {best_mrr:.4f}')

    for stage_name, dimensions in STAGES:
        results = []
        for overrides in product(dimensions):
            config = replace(best, **overrides)
            rows = evaluate(config, train, pools)
            results.append((rows['overall']['mrr'], overrides, rows))
        results.sort(key=lambda t: t[0], reverse=True)
        top_mrr, top_overrides, top_rows = results[0]
        log(f'[{stage_name}] best {top_overrides} -> train MRR {top_mrr:.4f} '
            f'(muni top-1 {top_rows["municipality"]["top1"]:.3f}, '
            f'parish top-1 {top_rows["parish"]["top1"]:.3f}, '
            f'church top-1 {top_rows["church"]["top1"]:.3f})')
        for mrr, overrides, _rows in results[1:4]:
            log(f'    runner-up {overrides} -> {mrr:.4f}')
        if top_mrr >= best_mrr:
            best, best_mrr = replace(best, **top_overrides), top_mrr

    # coordinate-wise refinement around the winner on the numeric weights
    for field in REFINED_FIELDS:
        for value in refine(getattr(best, field)):
            config = replace(best, **{field: value})
            mrr = evaluate(config, train, pools)['overall']['mrr']
            if mrr > best_mrr:
                best, best_mrr = config, mrr
    log(f'refined winner: {best} -> train MRR {best_mrr:.4f}')

    winner_all = evaluate(best, all_hits, pools)
    runs = {
        'replay (live code) / all': replay_summary,
        'winner / all': winner_all,
        'winner / validation': evaluate(best, val, pools),
        'winner / train': evaluate(best, train, pools),
    }
    log(render(runs))
    log('gates (on all hits, winner vs live replay):')
    log(f"  municipality top-1 {winner_all['municipality']['top1']:.3f} >= "
        f"{replay_summary['municipality']['top1']:.3f}: "
        f"{winner_all['municipality']['top1'] >= replay_summary['municipality']['top1']}")
    log(f"  overall MRR {winner_all['overall']['mrr']:.3f} >= "
        f"{replay_summary['overall']['mrr']:.3f}: "
        f"{winner_all['overall']['mrr'] >= replay_summary['overall']['mrr']}")
    log(f"  parish top-1 {winner_all['parish']['top1']:.3f} > "
        f"{replay_summary['parish']['top1']:.3f}: "
        f"{winner_all['parish']['top1'] > replay_summary['parish']['top1']}")

    return best
