from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from django.contrib.gis.db.models import Collect, Extent
from django.contrib.gis.db.models.functions import Distance, Centroid
from django.contrib.gis.geos import Point, Polygon
from django.db.models import QuerySet, OuterRef, Subquery, Exists, Q, \
    Count, Case, When
from django.utils.timezone import make_aware
from pydantic import BaseModel

from front.utils.city_utils import get_municipality_name
from registry.models import Church, Website, Diocese
from scheduling.models import IndexEvent
from scheduling.utils.date_utils import time_from_minutes

DEFAULT_LIMIT = 40
MAX_WEBSITES_IN_RESULTS = 10
DEFAULT_SEARCH_BOX = [41.787, 51.754, -9.162, 15.183]  # min_lat, max_lat, min_lng, max_lng


###########
# OBJECTS #
###########

class TimeFilter(BaseModel):
    day_filter: date | None
    hour_min: int | None
    hour_max: int | None
    legacy_search: bool = False
    limit: int = DEFAULT_LIMIT

    def is_null(self):
        return self.day_filter is None \
            and (self.hour_min is None or self.hour_min == 0) \
            and (self.hour_max is None or self.hour_max == 24 * 60 - 1)


@dataclass
class SearchResult:
    index_events: list[IndexEvent]
    churches: list[Church]
    too_many_results: bool
    events_truncated_by_website_uuid: dict[UUID, bool]


###############
# QUERY UTILS #
###############

def build_event_subquery(time_filter: TimeFilter):
    event_query = IndexEvent.objects.filter(church_id=OuterRef('pk'))
    event_query = add_event_filters(event_query, time_filter)

    return event_query


def build_base_church_query() -> QuerySet[Church]:
    return Church.objects.filter(is_active=True, parish__website__is_active=True)


def build_church_query(time_filter: TimeFilter) -> QuerySet[Church]:
    event_query = build_event_subquery(time_filter).order_by(
        'day',
        'start_time'
    ).values('uuid')

    church_query = build_base_church_query().select_related('parish__website')
    if time_filter.legacy_search:
        church_query = church_query.prefetch_related('parish__website__reports')
    church_query = church_query.annotate(next_event_uuid=Subquery(event_query[:1])) \
        .only("name",
              "address",
              "city",
              "zipcode",
              "location",
              "parish__uuid",
              "parish__diocese_id",
              "parish__website__uuid",
              "parish__website__name",
              "parish__website__home_url",
              )

    if not time_filter.is_null():
        church_query = church_query.filter(next_event_uuid__isnull=False)

    return church_query


def build_events_query(church_by_uuid: dict[UUID, Church],
                       time_filter: TimeFilter) -> QuerySet[IndexEvent]:
    event_query = IndexEvent.objects \
        .filter(church__uuid__in=church_by_uuid.keys())
    event_query = add_event_filters(event_query, time_filter)

    return event_query


def add_event_filters(event_query: QuerySet[IndexEvent],
                      time_filter: TimeFilter) -> QuerySet[IndexEvent]:
    event_query = event_query.filter(indexed_end_tz_datetime__gte=make_aware(datetime.now()))

    if time_filter.day_filter:
        event_query = event_query.filter(day=time_filter.day_filter)

    if time_filter.hour_min is not None or time_filter.hour_max is not None:
        hour_min = time_filter.hour_min or 0
        hour_max = time_filter.hour_max or 24 * 60 - 1
        event_query = event_query.filter(indexed_end_time__gte=time_from_minutes(hour_min),
                                         start_time__lte=time_from_minutes(hour_max))
    return event_query


def truncate_results(church_query: QuerySet[Church],
                     time_filter: TimeFilter
                     ) -> SearchResult:
    churches = list(church_query.all()[:time_filter.limit])

    if not time_filter.legacy_search:
        church_by_uuid = {church.uuid: church for church in churches}
        events = fetch_events(church_by_uuid, time_filter)
        all_churches_have_events = all(church.next_event_uuid is not None for church in churches)
        events_truncated_by_website_uuid = {church.parish.website.uuid: False
                                            for church in churches}
    else:
        non_truncated_count = 0
        non_truncated_churches = []
        truncated_churches = []

        all_churches_have_events = True

        events_truncated_by_website_uuid = {}
        for church in churches:
            website_uuid = church.parish.website.uuid
            if website_uuid not in events_truncated_by_website_uuid:
                if non_truncated_count >= MAX_WEBSITES_IN_RESULTS:
                    events_truncated_by_website_uuid[website_uuid] = True
                else:
                    events_truncated_by_website_uuid[website_uuid] = False
                    non_truncated_count += 1

            if events_truncated_by_website_uuid[website_uuid]:
                truncated_churches.append(church)
            else:
                non_truncated_churches.append(church)

            if church.next_event_uuid is None:
                all_churches_have_events = False

        non_truncated_church_by_uuid = {church.uuid: church for church in non_truncated_churches}
        truncated_church_by_uuid = {church.uuid: church for church in truncated_churches}
        events = fetch_events(non_truncated_church_by_uuid, time_filter) \
            + fetch_next_event(truncated_church_by_uuid)

    return SearchResult(
        index_events=events,
        churches=churches,
        too_many_results=all_churches_have_events and len(churches) == time_filter.limit,
        events_truncated_by_website_uuid=events_truncated_by_website_uuid
    )


def fetch_events(church_by_uuid: dict[UUID, Church],
                 time_filter: TimeFilter) -> list[IndexEvent]:
    events = build_events_query(church_by_uuid, time_filter).all()
    for event in events:
        event.church = church_by_uuid.get(event.church_id)

    return list(events)


def fetch_next_event(church_by_uuid: dict[UUID, Church]) -> list[IndexEvent]:
    events_uuid = [church.next_event_uuid for church in church_by_uuid.values()
                   if church.next_event_uuid]
    events = IndexEvent.objects.filter(uuid__in=events_uuid)

    for event in events:
        event.church = church_by_uuid.get(event.church_id)

    return list(events)


def filter_in_box(church_query: QuerySet[Church], min_lat, min_long, max_lat, max_long
                  ) -> QuerySet[Church]:
    polygon = Polygon.from_bbox((min_long, min_lat, max_long, max_lat))
    return church_query.filter(location__within=polygon)


###########
# QUERIES #
###########

def get_churches_around(center, time_filter: TimeFilter,
                        radius: float = 0.045  # 0.045 degrees is ~5km
                        ) -> SearchResult:
    latitude, longitude = center
    center_as_point = Point(x=longitude, y=latitude)

    church_query = build_church_query(time_filter) \
        .filter(location__dwithin=(center_as_point, radius)) \
        .annotate(distance=Distance('location', center_as_point)) \
        .order_by('distance')
    if not church_query.exists():
        print('try wider search')
        return get_churches_around(center, time_filter,
                                   0.16  # 0.16 degrees is ~18km, Granville
                                   )

    return truncate_results(church_query, time_filter)


def get_churches_in_box(min_lat, min_long, max_lat, max_long, time_filter: TimeFilter
                        ) -> SearchResult:
    church_query = filter_in_box(build_church_query(time_filter),
                                 min_lat, min_long, max_lat, max_long)\
        .annotate(has_event=Exists(build_event_subquery(time_filter)))\
        .order_by(
        '-has_event',
        '-parish__website__nb_recent_hits'
    )

    return truncate_results(church_query, time_filter)


def get_churches_by_website(
        website: Website,
        time_filter: TimeFilter,
) -> SearchResult:
    church_query = build_church_query(time_filter)\
        .filter(parish__website=website)

    return truncate_results(church_query, time_filter)


def get_churches_by_uuid(
        church_uuid: UUID,
        time_filter: TimeFilter,
) -> SearchResult:
    church_query = build_church_query(time_filter)\
        .filter(uuid=church_uuid)

    return truncate_results(church_query, time_filter)


def get_churches_by_diocese(
        diocese: Diocese,
        time_filter: TimeFilter,
) -> SearchResult:
    event_query = build_event_subquery(time_filter)
    church_query = build_church_query(time_filter).annotate(has_event=Exists(event_query))\
        .filter(parish__diocese=diocese)\
        .order_by(
        '-has_event',
        '-parish__website__nb_recent_hits'
    )

    return truncate_results(church_query, time_filter)


def get_popular_churches(min_lat, min_long, max_lat, max_long, time_filter: TimeFilter,
                         ) -> SearchResult:
    event_query = build_event_subquery(time_filter)
    church_query = filter_in_box(build_church_query(time_filter),
                                 min_lat, min_long, max_lat, max_long)\
        .annotate(has_event=Exists(event_query))\
        .order_by(
        '-has_event',
        '-parish__website__is_best_diocese_hit',
        '-parish__website__nb_recent_hits',
    )

    return truncate_results(church_query, time_filter)


###############
# AGGREGATION #
###############

class AggregationItem(BaseModel):
    type: Literal['diocese', 'parish', 'municipality']
    name: str
    church_count: int
    church_with_event_count: int
    centroid_latitude: float
    centroid_longitude: float
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float
    identifiers: list


def get_count_per_area(
        min_lat, min_long, max_lat, max_long,
        time_filter: TimeFilter,
        area_type: Literal['diocese', 'parish', 'municipality'],
        area_name_keys: list[str],
        identifier_keys: list[str],
) -> list[AggregationItem]:
    church_query = filter_in_box(build_base_church_query(), min_lat, min_long, max_lat, max_long)

    if not time_filter.is_null():
        church_query = church_query \
            .annotate(has_event=Exists(build_event_subquery(time_filter))) \
            .filter(has_event=True)

    church_query = church_query \
        .values(*set(area_name_keys + identifier_keys)) \
        .annotate(church_count=Count('uuid'),
                  centroid=Centroid(Collect('location')),
                  bounds=Extent('location'),
                  )

    if time_filter.is_null():
        church_query = church_query \
            .annotate(church_with_event_count=Count(Case(
                When(Exists(build_event_subquery(time_filter)), then='uuid'),
                default=None,
            )))

    results = []
    for row in church_query.all():
        min_longitude, min_latitude, max_longitude, max_latitude = row["bounds"]
        results.append(AggregationItem(
            type=area_type,
            name=';'.join(row[k] for k in area_name_keys),
            church_count=row['church_count'],
            church_with_event_count=row['church_with_event_count'] if time_filter.is_null()
            else row['church_count'],
            centroid_latitude=row['centroid'].y,
            centroid_longitude=row['centroid'].x,
            min_latitude=min_latitude,
            max_latitude=max_latitude,
            min_longitude=min_longitude,
            max_longitude=max_longitude,
            identifiers=[row[k] for k in identifier_keys],
        ))

    return results


def get_count_per_diocese(
    min_lat, min_long, max_lat, max_long,
    time_filter: TimeFilter,
) -> list[AggregationItem]:
    return get_count_per_area(
        min_lat, min_long, max_lat, max_long,
        time_filter,
        area_type='diocese',
        area_name_keys=['parish__diocese__name'],
        identifier_keys=['parish__diocese__uuid'],
    )


def get_count_per_parish(
    min_lat, min_long, max_lat, max_long,
    time_filter: TimeFilter,
) -> list[AggregationItem]:
    return get_count_per_area(
        min_lat, min_long, max_lat, max_long,
        time_filter,
        area_type='parish',
        area_name_keys=['parish__name'],
        identifier_keys=['parish__uuid'],
    )


def get_count_per_municipality(
    min_lat, min_long, max_lat, max_long,
    time_filter: TimeFilter,
) -> list[AggregationItem]:
    results = get_count_per_area(
        min_lat, min_long, max_lat, max_long,
        time_filter,
        area_type='municipality',
        area_name_keys=['city', 'zipcode'],
        identifier_keys=['city', 'zipcode'],
    )
    count_by_city = {}
    for item in results:
        city, zipcode = item.name.split(';')
        count_by_city.setdefault(city, 0)
        count_by_city[city] += 1
    for item in results:
        city, zipcode = item.name.split(';')
        if count_by_city[city] == 1:
            item.name = city
        else:
            item.name = get_municipality_name(city, zipcode)

    return results


def get_churches_in_area(aggregations: list[AggregationItem],
                         min_lat: float | None,
                         min_lng: float | None,
                         max_lat: float | None,
                         max_lng: float | None,
                         time_filter: TimeFilter
                         ) -> SearchResult:
    if not aggregations:
        return SearchResult(
            index_events=[],
            churches=[],
            too_many_results=False,
            events_truncated_by_website_uuid={}
        )

    assert len(set(map(lambda a: a.type, aggregations))) == 1, \
        "All aggregations must be of the same type (diocese, parish, municipality)"

    church_query = filter_in_box(build_church_query(time_filter),
                                 min_lat, min_lng, max_lat, max_lng)

    aggregations_type = aggregations[0].type
    if aggregations_type == 'diocese':
        assert all(len(a.identifiers) == 1 for a in aggregations), \
            "Diocese aggregations must have a single identifier (diocese UUID)"
        church_query = church_query.filter(
            parish__diocese__uuid__in=[a.identifiers[0] for a in aggregations])
    elif aggregations_type == 'parish':
        assert all(len(a.identifiers) == 1 for a in aggregations), \
            "Parish aggregations must have a single identifier (parish UUID)"
        church_query = church_query.filter(
            parish__uuid__in=[a.identifiers[0] for a in aggregations])
    elif aggregations_type == 'municipality':
        assert all(len(a.identifiers) == 2 for a in aggregations), \
            "Municipality aggregations must have two identifiers (city, zipcode)"
        query = Q()
        for a in aggregations:
            city, zipcode = a.identifiers
            query |= Q(city=city, zipcode=zipcode)
        church_query = church_query.filter(query)

    return truncate_results(church_query, time_filter)


################
# DIOCESE LIST #
################

class BoundingBox(BaseModel):
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float


def get_dioceses_bounding_box() -> list[tuple[Diocese, BoundingBox]]:
    dioceses = Diocese.objects \
        .annotate(bounds=Extent('parishes__churches__location')).all()

    results = []
    for diocese in dioceses:
        min_longitude, min_latitude, max_longitude, max_latitude = diocese.bounds
        bounding_box = BoundingBox(
            min_latitude=min_latitude,
            min_longitude=min_longitude,
            max_latitude=max_latitude,
            max_longitude=max_longitude,
        )
        results.append((diocese, bounding_box))
    return results
