"""Pure-Python candidate scorer over cached pools — the exact formula the service will get.

Replicates the merge semantics of get_aggregated_response: each source truncated to 15 by
score, then global sort, dedupe by url keeping first, truncate to 15.
"""
import math
from dataclasses import dataclass, replace  # noqa: F401  (replace used by grid_search)

MAX_RESULTS = 15


@dataclass(frozen=True)
class Config:
    prefix_w: float = 50.0
    substr_w: float = 0.0
    sim_w: float = 10.0
    word_w: float = 0.0
    geo_w: float = 12.0
    pop_w: float = 20.0
    half_life_km: float = 50.0
    geo_shape: str = 'inv'      # 'inv' = 1/(1+d/h) ; 'exp' = exp(-d*ln2/h)
    boost_municipality: float = 0.0
    boost_parish: float = 0.0   # applies to parish AND website rows (both shown as 'parish')
    boost_church: float = 0.0


def geo_score(distance_m: float | None, config: Config) -> float:
    if distance_m is None:
        return 0.0
    h = config.half_life_km * 1000.0
    if config.geo_shape == 'exp':
        return math.exp(-distance_m * math.log(2) / h)
    return 1.0 / (1.0 + distance_m / h)


def row_score(row: dict, config: Config) -> float:
    boost = {'municipality': config.boost_municipality, 'parish': config.boost_parish,
             'church': config.boost_church}[row['type']]
    return (config.prefix_w * row['s_prefix']
            + config.substr_w * row['s_substr']
            + config.sim_w * row['s_sim']
            + config.word_w * row['s_word']
            + config.geo_w * geo_score(row['distance_m'], config)
            + config.pop_w * row['s_pop']
            + boost)


def rank_pools(pools_for_key: dict[str, list[dict]], config: Config) -> list[str]:
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
