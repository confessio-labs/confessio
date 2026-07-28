"""Tuning constants of the autocomplete ranking score.

Used by front.services.search.autocomplete_service (the live formula) and by the registry
`autocomplete_tuning` command (weight defaults and the pure-Python mirror), so both always
agree. Re-tune with `python manage.py autocomplete_tuning --mode grid-search`.
"""

MAX_AUTOCOMPLETE_RESULTS = 15

# Weights of the shared ranking score, computed in SQL for all four sources so their results are
# directly comparable. Grid-searched on 4143 recorded autocomplete hits (front_autocompletehit,
# Apr-Jul 2026) replayed through the retrieval, with a time-split validation (tune <= Jun 15,
# validate after). Baseline (previous two-scorer ranking) vs this score, top-1/MRR on all hits:
# overall .756/.824 -> .758/.826, municipality .867/.902 -> .865/.899, parish .215/.450 ->
# .248/.502, church .355/.525 -> .355/.506; on the validation split parish top-1 goes
# .297 -> .441 and municipality .865 -> .877.
PREFIX_WEIGHT = 50.0
# Exact-substring bonus: parish and church names are long ('Paroisse Saint-Leger en
# Saint-Maixentais'), where trigram similarity is mechanically low for a short query.
SUBSTRING_WEIGHT = 10.0
SIMILARITY_WEIGHT = 6.0
# word_similarity() scores the query against the best-matching word span, so it is the string
# signal that works on long names ('saint maixentais' scores 1.0 vs 0.49 plain similarity).
WORD_SIMILARITY_WEIGHT = 15.0
GEO_WEIGHT = 18.0
POPULATION_WEIGHT = 20.0
# ln(2_500_000), a bit above the most populated commune, so that s_pop stays in [0, 1]
MAX_LN_POPULATION = 14.73
# Traffic popularity of parish/website/church rows (Website.nb_recent_hits), the analogue of
# POPULATION_WEIGHT for the three non-city sources. A separate knob on purpose: no row carries
# both signals, so nothing is lost by splitting them, whereas a shared weight would make every
# parish-ranking adjustment silently reshuffle the municipality ranking — the very regression
# the grid search gates against.
# Ships at 0.0: the recorded hits that would tune it stop at 2026-06-27, when the Next.js front
# took over `/` without ever calling POST /front/api/autocomplete/hits (weekly picks fell
# 426 -> 27 while autocomplete queries rose 443 -> 8595). Set it from a grid search once the
# beacon is restored and fresh hits have accumulated.
HITS_WEIGHT = 0.0
# ln(1000), about twice the largest observed nb_recent_hits (548, median 4), leaving headroom
# for growth. Only the ratio HITS_WEIGHT / MAX_LN_HITS matters to the ranking, so this is a
# readability choice rather than a tuning knob.
MAX_LN_HITS = 6.91
# Geo proximity is an ADDITIVE bonus with a fast exponential decay: score halves every 30 km.
# The previous ranking MULTIPLIED name similarity by 50km/(50km+d), which buried far exact
# matches: 34% of recorded picks are >50 km away and 26% >200 km (trips, home towns), and
# rank>0 picks were measurably farther than rank-0 picks (median 30.6 km vs 19.4 km). Additive
# geo can never bury an exact name match; it acts as a local tie-breaker.
GEO_HALF_LIFE_METERS = 30000.0
# Geo and population are multiplied by min(1, best_string_signal / threshold), where
# best_string_signal = max(s_prefix, s_substr, s_word): location and size break ties among good
# matches but cannot outvote them. Without the gate a nearby metropolis with a junk trigram
# match (word similarity 0.38) collected its full ~35 geo+pop points and beat any perfect
# non-prefix match, which caps around 34 ('saint yves de la mer' typed in Paris ranked the
# exact-matching parish 5th behind Saint-Denis). Short prefix queries are untouched (prefix or
# word similarity is 1.0 there). Measured on the recorded hits: parish/church metrics and
# recall@15 unchanged, municipality top-1 -0.005 — over half of the changed contexts are
# parish-intent queries ('rouen cathedrale', 'paroisse athis') whose parish now outranks the
# picked city. 0.45 fixed the Paris showcase by only 0.2 points, 0.5 wins it by 3: hence 0.5.
GEO_POP_GATE_THRESHOLD = 0.5
# Per-type additive boosts, same grid search. Municipalities need none (prefix + population
# already carry them); parishes and churches were systematically outranked before (parish picks
# landed at rank 0 only 40% of the time, vs 88% for municipalities). Keyed by DISPLAYED result
# type: website results are emitted with type='parish' (from_website) and get the parish boost —
# the recorded hits only distinguish these three types, so a separate website boost could not
# be tuned anyway.
TYPE_BOOSTS = {'municipality': 0.0, 'parish': 5.0, 'church': 4.0}
