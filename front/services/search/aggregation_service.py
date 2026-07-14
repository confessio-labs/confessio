from front.services.search.search_service import get_churches_in_box, get_count_per_diocese, \
    TimeFilter, get_count_per_municipality, get_count_per_parish, \
    get_churches_in_area, get_churches_around, AggregationItem, \
    DEFAULT_SEARCH_BOX, SearchResult


def get_search_results(
        latitude: float | None,
        longitude: float | None,
        min_lat: float | None,
        min_lng: float | None,
        max_lat: float | None,
        max_lng: float | None,
        time_filter: TimeFilter,
) -> tuple[SearchResult, list[AggregationItem]]:
    if min_lat and min_lng and max_lat and max_lng:
        search_result = get_churches_in_box(min_lat, min_lng, max_lat, max_lng, time_filter)
        aggregations = []
        if len(search_result.churches) == time_filter.limit:
            diocese_count = len(set(church.parish.diocese_id for church in search_result.churches))
            if diocese_count <= time_filter.limit:
                municipality_count = len(set((church.city, church.zipcode)
                                             for church in search_result.churches))
                parish_count = len(set(church.parish.uuid for church in search_result.churches))

                if parish_count > municipality_count:
                    # Search in big cities, many parishes, few municipalities
                    aggregations = get_count_per_municipality(min_lat, min_lng, max_lat, max_lng,
                                                              time_filter)
                else:
                    # Search in countryside, many municipalities, few parishes
                    aggregations = get_count_per_parish(min_lat, min_lng, max_lat, max_lng,
                                                        time_filter)

            if not aggregations or len(aggregations) > time_filter.limit:
                # Too granular, fallback on diocese aggregation
                aggregations = get_count_per_diocese(min_lat, min_lng, max_lat, max_lng,
                                                     time_filter)

            singleton_aggregations = list(filter(lambda a: a.church_count == 1, aggregations))
            search_result = get_churches_in_area(singleton_aggregations,
                                                 min_lat, min_lng, max_lat, max_lng,
                                                 time_filter)
            aggregations = list(filter(lambda a: a.church_count > 1, aggregations))
    elif latitude and longitude:
        center = [latitude, longitude]
        search_result = get_churches_around(center, time_filter)
        aggregations = []
    else:
        min_lat, max_lat, min_lng, max_lng = DEFAULT_SEARCH_BOX
        return get_search_results(latitude, longitude, min_lat, min_lng, max_lat, max_lng,
                                  time_filter)

    return search_result, aggregations
