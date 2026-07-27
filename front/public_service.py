from uuid import UUID

from front.services.card.church_color_service import get_church_color_by_uuid
from front.services.search.autocomplete_service import (
    GEO_HALF_LIFE_METERS, GEO_WEIGHT, MAX_LN_POPULATION, POPULATION_WEIGHT, PREFIX_WEIGHT,
    SIMILARITY_WEIGHT, SUBSTRING_WEIGHT, TYPE_BOOSTS, WORD_SIMILARITY_WEIGHT,
    AutocompleteResult, annotate_search_score, get_aggregated_response, long_name_predicate)
from registry.models import Church
from scheduling.public_model import SourcedSchedulesList

# Autocomplete internals re-exported for the registry `autocomplete_tuning` command
# (cross-module imports must go through a public_*.py file).
AUTOCOMPLETE_MAX_LN_POPULATION = MAX_LN_POPULATION
AUTOCOMPLETE_TYPE_BOOSTS = TYPE_BOOSTS
AUTOCOMPLETE_GEO_HALF_LIFE_METERS = GEO_HALF_LIFE_METERS
AUTOCOMPLETE_WEIGHTS = {
    'prefix': PREFIX_WEIGHT,
    'substr': SUBSTRING_WEIGHT,
    'sim': SIMILARITY_WEIGHT,
    'word': WORD_SIMILARITY_WEIGHT,
    'geo': GEO_WEIGHT,
    'pop': POPULATION_WEIGHT,
}


def front_get_church_color_by_uuid(sourced_schedules_list: SourcedSchedulesList,
                                   church_by_id: dict[int, Church]) -> dict[UUID, str]:
    return get_church_color_by_uuid(sourced_schedules_list, church_by_id)


async def front_get_autocomplete_response(query: str, latitude: float | None,
                                          longitude: float | None
                                          ) -> list[AutocompleteResult]:
    return await get_aggregated_response(query, latitude, longitude)


def front_annotate_autocomplete_search_score(qs, query_term, user_point, geo_field,
                                             type_boost, pop_expression=None):
    return annotate_search_score(qs, query_term, user_point, geo_field, type_boost,
                                 pop_expression=pop_expression)


def front_autocomplete_long_name_predicate(query_term: str):
    return long_name_predicate(query_term)
