import json

from django import template
from django.contrib.gis.geos import Point
from django.template.loader import render_to_string

from front.services.search.map_service import get_map_with_single_location

register = template.Library()


TOOL_LABELS = {
    # Tools autonomes (lecture seule)
    'run_sql': 'Requête SQL (lecture seule)',
    'describe_schema': 'Explorer le schéma de la base',
    'visit_url': 'Consulter une page web',
    'google_search': 'Recherche Google',
    'google_maps_search': 'Recherche Google Maps',
    # Tools proposés (mutation, soumis à validation)
    'assign_website': 'Rattacher cette discussion à une paroisse',
    'add_church': 'Créer une église',
    'update_church': 'Modifier une église',
    'delete_church': 'Supprimer une église',
    'add_parish': 'Créer une paroisse',
    'update_parish': 'Modifier une paroisse',
    'delete_parish': 'Supprimer une paroisse',
    'add_website': 'Créer un site web',
    'update_website': 'Modifier un site web',
    'delete_website': 'Supprimer un site web',
    'trigger_recrawl': 'Relancer le crawl d’un site',
    'report_bug': 'Signaler un bug',
}


@register.filter
def tool_label(value):
    return TOOL_LABELS.get(value, value)


@register.filter
def to_pretty_json(value):
    if value is None:
        return ''
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


@register.filter
def position_map(tool_args):
    """Render a Leaflet/OSM mini-map for a proposed tool whose args carry latitude/longitude.

    Returns '' when the coordinates are absent (e.g. an update_church without a position change),
    so the template can render it unconditionally.
    """
    if not isinstance(tool_args, dict):
        return ''
    latitude, longitude = tool_args.get('latitude'), tool_args.get('longitude')
    if latitude is None or longitude is None:
        return ''
    folium_map = get_map_with_single_location(Point(longitude, latitude, srid=4326))
    return render_to_string('displays/location_display.html',
                            {'map_html': folium_map._repr_html_()})
