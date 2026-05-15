import json
import os
import random
from datetime import date, datetime
from statistics import mean
from typing import List, Tuple, Dict, Optional
from uuid import UUID

from django.contrib.gis.geos import Point
from django.utils.translation import gettext as _
from folium import Map, Icon, Popup, Marker

from front.services.card.website_events_service import WebsiteEvents
from registry.models import Church
from scheduling.utils.date_utils import format_datetime_with_locale


###########
# DISPLAY #
###########

def get_center(churches: List[Church]) -> List[float]:
    latitude = mean(map(lambda c: c.location.y, churches))
    longitude = mean(map(lambda c: c.location.x, churches))

    return [latitude, longitude]


def get_bounds(churches: List[Church]) -> Tuple[float, float, float, float]:
    latitudes = list(map(lambda c: c.location.y, churches))
    longitudes = list(map(lambda c: c.location.x, churches))

    return min(latitudes), max(latitudes), min(longitudes), max(longitudes)


def get_latitude_longitude(point):
    return [point.coords[1], point.coords[0]]


def get_popup_and_color(church: Church,
                        website_events: WebsiteEvents
                        ) -> Tuple[str, str]:
    next_event = website_events.next_event_in_church(church) \
        if website_events else None
    if next_event is not None:
        start = datetime.combine(next_event.day, next_event.start_time)
        date_str = format_datetime_with_locale(start, "%A %d %B", 'fr_FR.UTF-8')
        year_str = f" {start.year}" \
            if start.year != date.today().year else ''
        wording = f'{_("NextEvent")}<br>le {date_str.lower()}{year_str} à {start:%H:%M}'
        color = 'darkblue'
    elif website_events.confession_exists:
        wording = _("ConfessionsExist")
        color = 'blue'
    else:
        wording = _("NoConfessionFound")
        color = 'lightgray'

    link_wording = _("JumpBelow")
    popup_html = f"""
        <b>{church.name}</b><br>
        {wording}<br>
        <a href="#{church.parish.website.uuid}" target="_parent">{link_wording}</a>
    """

    return popup_html, color


def prepare_map(center, churches: List[Church], bounds,
                events_by_website: dict[UUID, WebsiteEvents],
                is_around_me: bool
                ) -> Tuple[Map, Dict[UUID, str]]:
    # Create Map Object
    jawg_api_key = os.environ[random.choice(['JAWG_API_KEY1', 'JAWG_API_KEY2', 'JAWG_API_KEY3'])]
    folium_map = Map(
        location=center,
        tiles="https://tile.jawg.io/jawg-sunny/{z}/{x}/{y}{r}.png?"
              f"access-token={jawg_api_key}",
        attr='<a href="https://jawg.io" title="Tiles Courtesy of Jawg Maps" target="_blank">'
             '&copy; <b>Jawg</b>Maps</a> &copy; <a href="https://www.openstreetmap.org/copyright">'
             'OpenStreetMap</a> contributors',
    )

    if is_around_me:
        marker = Marker(center,
                        tooltip='Votre position',
                        icon=Icon(icon='crosshairs', prefix='fa', color='lightred'))
        marker.add_to(folium_map)

    # We save marker_names, they will be displayed in template and used in javascript
    church_marker_names_by_website = {}

    for church in churches:
        website_uuid = church.parish.website.uuid
        website_events = events_by_website.get(website_uuid, None)

        tootltip_text = f'{church.name}'
        popup_html, color = get_popup_and_color(church, website_events)
        marker = Marker(get_latitude_longitude(church.location),
                        tooltip=tootltip_text,
                        popup=Popup(html=popup_html, max_width=None),
                        icon=Icon(icon='cross', prefix='fa', color=color))
        church_marker_names_by_website\
            .setdefault(website_uuid, {})[str(church.uuid)] = marker.get_name()
        marker.add_to(folium_map)

    if bounds or len(churches) > 0:
        if bounds:
            min_lat, max_lat, min_long, max_long = bounds
        else:
            min_lat, max_lat, min_long, max_long = get_bounds(churches)
        folium_map.fit_bounds([[min_lat, min_long],
                               [max_lat, max_long]])

    church_marker_names_json_by_website = {
        website_uuid: json.dumps(marker_names)
        for website_uuid, marker_names in church_marker_names_by_website.items()
    }

    return folium_map, church_marker_names_json_by_website


def get_map_with_single_location(location: Point) -> Map:
    folium_map = Map(
        location=get_latitude_longitude(location),
        zoom_start=16,
    )
    marker = Marker(get_latitude_longitude(location),
                    icon=Icon(icon='cross', prefix='fa', color='blue'))
    marker.add_to(folium_map)

    return folium_map


def get_map_with_multiple_locations(churches: list[Church]) -> Optional[Map]:
    if not churches:
        return None

    folium_map = Map(
        location=get_center(churches),
        zoom_start=16,
    )

    for church in churches:
        marker = Marker(get_latitude_longitude(church.location),
                        tooltip=f'{church.name}',
                        icon=Icon(icon='cross', prefix='fa', color='blue'))
        marker.add_to(folium_map)

    min_lat, max_lat, min_long, max_long = get_bounds(churches)
    folium_map.fit_bounds([[min_lat, min_long],
                           [max_lat, max_long]])

    return folium_map


def get_map_with_alternative_locations(church: Church, similar_churches: list[Church]) -> Map:
    folium_map = Map(
        location=get_latitude_longitude(church.location),
        zoom_start=16,
    )
    marker = Marker(get_latitude_longitude(church.location),
                    tooltip=church.name,
                    icon=Icon(icon='cross', prefix='fa', color='blue'))
    marker.add_to(folium_map)

    min_distance = None
    min_church = None
    for i, similar_church in enumerate(similar_churches):
        color = 'green' if similar_church.messesinfo_id is None else 'orange'
        marker = Marker(get_latitude_longitude(similar_church.location),
                        tooltip=f'{similar_church.name}',
                        icon=Icon(icon=f'{i + 1}', prefix='fa', color=color))
        marker.add_to(folium_map)
        distance_to_church = church.location.distance(similar_church.location)
        if min_distance is None or distance_to_church < min_distance:
            min_distance = distance_to_church
            min_church = similar_church

    if min_church:
        folium_map.fit_bounds([
            get_latitude_longitude(church.location),
            get_latitude_longitude(min_church.location)
        ])

    return folium_map


##################
# WEBSITE CITIES #
##################

def get_cities_label(churches: list[Church]) -> str:
    cities_count = {}
    for church in churches:
        if not church.city:
            continue

        church_city = church.city.strip().title()

        cities_count[church_city] = cities_count.get(church_city, 0) + 1

    if len(cities_count) > 4:
        # too many cities
        return ''

    if len(cities_count) == 0:
        # no city
        return ''

    if len(cities_count) == 1:
        # only one city
        return list(cities_count.keys())[0]

    # get city name by order of count
    cities_names = [name for name, count in
                    sorted(cities_count.items(), key=lambda item: item[1], reverse=True)]
    return ' ○ '.join(cities_names)
