"""Constants of the website traffic popularity signal (Website.nb_recent_hits).

A utils module rather than a service one so that both `front.services.search.popularity_service`
(which produces the counter) and the `autocomplete_tuning` command (which must exclude the hits
recorded inside this window from its corpus) can share the definition.
"""

# Length of the rolling window nb_recent_hits counts over.
POPULARITY_WINDOW_DAYS = 14
