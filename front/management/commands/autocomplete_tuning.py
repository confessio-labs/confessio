"""Replay recorded autocomplete hits to evaluate and re-tune the shared ranking score.

Modes:
  --mode replay       run every hit through the LIVE autocomplete service; report
                      top-1/top-3/MRR/recall@15 per type + agreement with recorded ranks.
  --mode candidate    re-rank cached candidate pools in pure Python with (overridable)
                      weights; report the same metrics + pool recall.
  --mode grid-search  staged grid search over the weights (needs a prior --mode replay
                      for the non-regression gates).

Caches (pickles, safe to delete) live in --cache-dir. The scoring weights come from
front.utils.autocomplete_constants so the defaults always match prod.
"""
import os
import pickle
from datetime import datetime, timedelta

from django.utils import timezone

from core.management.abstract_command import AbstractCommand
from front.services.search.autocomplete_pool_service import build_pools, report_pool_recall
from front.services.search.autocomplete_replay_service import (load_and_resolve_hits,
                                                               replay_live, report_agreement)
from front.utils.autocomplete_constants import (
    GEO_HALF_LIFE_METERS, GEO_POP_GATE_THRESHOLD, GEO_WEIGHT, POPULARITY_WEIGHT,
    POPULATION_WEIGHT, PREFIX_WEIGHT, SIMILARITY_WEIGHT, SUBSTRING_WEIGHT, TYPE_BOOSTS,
    WORD_SIMILARITY_WEIGHT)
from front.utils.autocomplete_metrics_utils import outcomes_from_ranked, render, summarize
from front.utils.autocomplete_scoring_utils import ScoringConfig, rank_pools
from front.utils.popularity_constants import POPULARITY_WINDOW_DAYS
from front.workflows.autocomplete_grid_search_workflow import run_grid_search

REPLAY_CACHE = 'replay.pkl'
# v2: pool rows carry s_population and s_popularity instead of a single s_pop. A stale v1 file
# would raise a KeyError rather than mislead, but rebuilding is what we actually want.
POOLS_CACHE = 'pools_v2.pkl'


class Command(AbstractCommand):
    help = "Replay recorded autocomplete hits to evaluate or re-tune the ranking score."

    def add_arguments(self, parser):
        parser.add_argument('--mode', choices=['replay', 'candidate', 'grid-search'],
                            required=True)
        parser.add_argument('--cache-dir', default='autocomplete_tuning_cache',
                            help='directory for pickle caches (gitignored, safe to delete)')
        parser.add_argument('--split-date', default=None,
                            help='train/validation split (ISO date); default: hits 80th'
                                 ' percentile by created_at')
        parser.add_argument('--hit-cutoff-days', type=int, default=POPULARITY_WINDOW_DAYS,
                            help='drop hits newer than now - N days: they sit inside the rolling'
                                 ' nb_recent_hits window and caused the popularity that would'
                                 ' rank them, which leaks into s_popularity. 0 disables it')
        parser.add_argument('--prefix-weight', type=float, default=PREFIX_WEIGHT)
        parser.add_argument('--substr-weight', type=float, default=SUBSTRING_WEIGHT)
        parser.add_argument('--sim-weight', type=float, default=SIMILARITY_WEIGHT)
        parser.add_argument('--word-weight', type=float, default=WORD_SIMILARITY_WEIGHT)
        parser.add_argument('--geo-weight', type=float, default=GEO_WEIGHT)
        parser.add_argument('--population-weight', type=float, default=POPULATION_WEIGHT,
                            help='weight of City.population, on municipality rows only')
        parser.add_argument('--popularity-weight', type=float, default=POPULARITY_WEIGHT,
                            help='weight of nb_recent_hits, on parish/website/church rows'
                                 ' only')
        parser.add_argument('--geo-half-life-km', type=float,
                            default=GEO_HALF_LIFE_METERS / 1000.0)
        parser.add_argument('--geo-shape', choices=['inv', 'exp'], default='exp')
        parser.add_argument('--gate-threshold', type=float, default=GEO_POP_GATE_THRESHOLD,
                            help='geo+pop are scaled by min(1, best_string_signal / T);'
                                 ' 0 disables the gate')
        parser.add_argument('--boost-municipality', type=float,
                            default=TYPE_BOOSTS['municipality'])
        parser.add_argument('--boost-parish', type=float, default=TYPE_BOOSTS['parish'])
        parser.add_argument('--boost-church', type=float, default=TYPE_BOOSTS['church'])

    def handle(self, *args, **options):
        self.cache_dir = options['cache_dir']
        os.makedirs(self.cache_dir, exist_ok=True)

        cutoff = None
        if options['hit_cutoff_days']:
            cutoff = timezone.now() - timedelta(days=options['hit_cutoff_days'])
            self.info(f'corpus cutoff {cutoff:%Y-%m-%d %H:%M}: dropping the hits recorded inside'
                      f" the {options['hit_cutoff_days']}-day nb_recent_hits window")

        self.info('Resolving recorded hits...')
        hits, skips = load_and_resolve_hits(max_created_at=cutoff)
        self.info(f'{len(hits)} hits resolved, {sum(skips.values())} skipped ({skips})')
        if not hits:
            self.error('No hit left to evaluate on.')
            return

        # The cutoff scales with the popularity window, so a wide window can quietly leave too
        # few hits to conclude anything. Say so rather than print confident metrics on a stub.
        nb_dropped = skips.get('inside-popularity-window', 0)
        if nb_dropped > len(hits):
            self.error(f'The cutoff dropped {nb_dropped} hits and kept only {len(hits)}: the'
                       f' popularity window is nearly as long as the recorded history. Per-type'
                       f' metrics below are computed on very few hits — pass --hit-cutoff-days'
                       f' explicitly if you want to trade leakage for corpus size.')

        if options['mode'] == 'replay':
            self.handle_replay(hits, skips)
        elif options['mode'] == 'candidate':
            self.handle_candidate(hits, skips, self.config_from_options(options))
        else:
            self.handle_grid_search(hits, options)

    @staticmethod
    def config_from_options(options) -> ScoringConfig:
        return ScoringConfig(
            prefix_w=options['prefix_weight'], substr_w=options['substr_weight'],
            sim_w=options['sim_weight'], word_w=options['word_weight'],
            geo_w=options['geo_weight'], population_w=options['population_weight'],
            popularity_w=options['popularity_weight'],
            half_life_km=options['geo_half_life_km'], geo_shape=options['geo_shape'],
            gate_threshold=options['gate_threshold'],
            boost_municipality=options['boost_municipality'],
            boost_parish=options['boost_parish'], boost_church=options['boost_church'])

    def cache_load(self, name):
        path = os.path.join(self.cache_dir, name)
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return pickle.load(f)
        return None

    def cache_save(self, name, obj):
        with open(os.path.join(self.cache_dir, name), 'wb') as f:
            pickle.dump(obj, f)

    def get_replay_ranked(self, hits) -> dict[tuple, list[str]]:
        cached = self.cache_load(REPLAY_CACHE) or {}
        keys = [h.key for h in hits]
        todo = len({k for k in keys if k not in cached})
        self.info(f'{len(cached)} live replays cached, {todo} to run')

        def on_batch(ranked, done, total):
            self.cache_save(REPLAY_CACHE, ranked)
            self.info(f'  {done}/{total} replayed')

        ranked = replay_live(keys, cached, on_batch)
        self.cache_save(REPLAY_CACHE, ranked)
        return ranked

    def get_pools(self, hits) -> dict[tuple, dict]:
        cached = self.cache_load(POOLS_CACHE) or {}
        keys = list({h.key for h in hits})
        self.info(f'{len(cached)} pools cached, {len([k for k in keys if k not in cached])}'
                  ' to build')

        def on_progress(pools, done, total):
            self.cache_save(POOLS_CACHE, pools)
            self.info(f'  {done}/{total} pools built')

        pools = build_pools(keys, cached, on_progress)
        self.cache_save(POOLS_CACHE, pools)
        return pools

    def split_hits(self, hits, options):
        if options['split_date']:
            split = datetime.fromisoformat(options['split_date'])
            if timezone.is_naive(split):
                split = timezone.make_aware(split)
        else:
            # default: 80/20 time split
            dates = sorted(h.created_at for h in hits)
            split = dates[int(len(dates) * 0.8)]
        train = [h for h in hits if h.created_at < split]
        val = [h for h in hits if h.created_at >= split]
        if not val:
            self.error(f'Empty validation split: --split-date {split:%Y-%m-%d} is at or after'
                       ' the corpus cutoff, so the validation numbers below mean nothing.')
        return train, val, split

    def handle_replay(self, hits, skips):
        ranked = self.get_replay_ranked(hits)
        self.info(report_agreement(hits, ranked))
        summary = summarize(outcomes_from_ranked(hits, ranked))
        self.success('\n' + render({'replay (live code)': summary}, skips))

    def handle_candidate(self, hits, skips, config: ScoringConfig):
        pools = self.get_pools(hits)
        for line in report_pool_recall(hits, pools):
            self.info(line)
        keys = {h.key for h in hits}
        ranked = {key: rank_pools(pools[key], config) for key in keys if key in pools}
        summary = summarize(outcomes_from_ranked(hits, ranked))
        self.info(f'config: {config}')
        self.success('\n' + render({'candidate': summary}, skips))

    def handle_grid_search(self, hits, options):
        replay_ranked = self.cache_load(REPLAY_CACHE)
        if not replay_ranked:
            self.error('No replay cache: run `autocomplete_tuning --mode replay` first '
                       '(the grid search gates compare against the live ranking).')
            return
        replay_summary = summarize(outcomes_from_ranked(hits, replay_ranked))
        pools = self.get_pools(hits)
        train, val, split = self.split_hits(hits, options)
        self.info(f'{len(train)} train hits, {len(val)} validation hits (split {split})')
        winner = run_grid_search(self.config_from_options(options), train, val, hits, pools,
                                 replay_summary, self.info)
        self.success(f'winner: {winner}')
