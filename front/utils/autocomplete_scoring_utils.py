"""Pure-Python mirror of the autocomplete SQL score, applied to cached candidate pools.

Mirrors front.services.search.autocomplete_service.annotate_search_score and the merge of
get_aggregated_response (each source truncated to 15 by score, global sort, dedupe by url
keeping first, truncate to 15). Both must stay in sync: `autocomplete_tuning --mode replay`
(live service) vs `--mode candidate` with the prod weights is the drift check.
"""
import math
from dataclasses import dataclass

from front.utils.autocomplete_constants import GEO_POP_GATE_THRESHOLD
from front.utils.autocomplete_constants import MAX_AUTOCOMPLETE_RESULTS as MAX_RESULTS


@dataclass(frozen=True)
class ScoringConfig:
    prefix_w: float
    substr_w: float
    sim_w: float
    word_w: float
    geo_w: float
    pop_w: float             # City.population, municipality rows only
    hits_w: float            # Website.nb_recent_hits, parish/website/church rows only
    half_life_km: float
    geo_shape: str = 'exp'      # 'exp' = exp(-d*ln2/h) ; 'inv' = 1/(1+d/h)
    boost_municipality: float = 0.0
    boost_parish: float = 0.0   # applies to parish AND website rows (both shown as 'parish')
    boost_church: float = 0.0
    # geo+pop are multiplied by min(1, best_string_signal / gate_threshold); <= 0 disables
    gate_threshold: float = GEO_POP_GATE_THRESHOLD


def geo_score(distance_m: float | None, config: ScoringConfig) -> float:
    if distance_m is None:
        return 0.0
    h = config.half_life_km * 1000.0
    if config.geo_shape == 'exp':
        return math.exp(-distance_m * math.log(2) / h)
    return 1.0 / (1.0 + distance_m / h)


def row_score(row: dict, config: ScoringConfig) -> float:
    boost = {'municipality': config.boost_municipality, 'parish': config.boost_parish,
             'church': config.boost_church}[row['type']]
    quality = max(row['s_prefix'], row['s_substr'], row['s_word'])
    gate = 1.0 if config.gate_threshold <= 0 \
        else min(1.0, quality / config.gate_threshold)
    # s_pop holds the commune population on municipality rows and the website traffic on the
    # other three, and the two never coexist on a row, so the type selects the weight. Mirrors
    # the pop_weight argument of annotate_search_score.
    pop_w = config.pop_w if row['type'] == 'municipality' else config.hits_w
    return (config.prefix_w * row['s_prefix']
            + config.substr_w * row['s_substr']
            + config.sim_w * row['s_sim']
            + config.word_w * row['s_word']
            + (config.geo_w * geo_score(row['distance_m'], config)
               + pop_w * row['s_pop']) * gate
            + boost)


def rank_pools(pools_for_key: dict[str, list[dict]], config: ScoringConfig) -> list[str]:
    """Ordered result URLs for one replay context under `config`."""
    merged = []
    for source_rows in pools_for_key.values():
        scored = sorted(((row_score(r, config), r) for r in source_rows),
                        key=lambda t: t[0], reverse=True)[:MAX_RESULTS]
        merged.extend(scored)
    merged.sort(key=lambda t: t[0], reverse=True)
    seen, urls = set(), []
    for _score, row in merged:
        if row['url'] not in seen:
            seen.add(row['url'])
            urls.append(row['url'])
    return urls[:MAX_RESULTS]
