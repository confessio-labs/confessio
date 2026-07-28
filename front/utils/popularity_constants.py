"""Constants of the website traffic popularity signal (Website.nb_recent_hits).

A utils module rather than a service one so that both `front.services.search.popularity_service`
(which produces the counter) and the `autocomplete_tuning` command (which must exclude the hits
recorded inside this window from its corpus) can share the definition.
"""

# Length of the rolling window nb_recent_hits counts over. 90 rather than 14 days because the
# counters are per entity: over two weeks most churches and websites sat on a handful of hits
# (median 3), where 90 days gives 2767 churches and 2303 websites a usable signal and lifts the
# median website to 27. Observed maxima stay far below the PositiveSmallIntegerField cap.
POPULARITY_WINDOW_DAYS = 90
