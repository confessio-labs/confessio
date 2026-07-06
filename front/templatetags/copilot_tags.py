import json

from django import template
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string

from front.services.search.map_service import get_map_with_single_location
from registry.models import Church, Diocese, Parish, Website

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


# Arg keys that carry a UUID -> (French label, model). Resolved to the entity name for display.
_UUID_FIELDS = {
    'website_uuid': ('Site', Website),
    'parish_uuid': ('Paroisse', Parish),
    'church_uuid': ('Église', Church),
    'diocese_uuid': ('Diocèse', Diocese),
}

# French labels for the remaining (non-UUID) arg keys of the proposed tools.
_ARG_LABELS = {
    'name': 'Nom',
    'city': 'Ville',
    'zipcode': 'Code postal',
    'address': 'Adresse',
    'latitude': 'Latitude',
    'longitude': 'Longitude',
    'home_url': 'URL',
    'is_active': 'Actif',
    'enabled_for_crawling': 'Crawl activé',
    'title': 'Titre',
    'details': 'Détails',
}


@register.filter
def humanize_tool_args(tool_args):
    """Turn a proposed tool's raw args into readable [{label, value}] rows.

    Every *_uuid is resolved to its entity name so the human validator can read and understand the
    action instead of an opaque UUID. Unknown keys fall back to the raw key/value.
    """
    if not isinstance(tool_args, dict):
        return []
    rows = []
    for key, value in tool_args.items():
        if value is None:
            continue
        if key in _UUID_FIELDS:
            label, model = _UUID_FIELDS[key]
            try:
                name = model.objects.filter(uuid=value).values_list('name', flat=True).first()
            except (ValueError, ValidationError, TypeError):
                name = None
            display = name or f'{value} (introuvable)'
        elif isinstance(value, bool):
            label, display = _ARG_LABELS.get(key, key), ('Oui' if value else 'Non')
        else:
            label, display = _ARG_LABELS.get(key, key), value
        rows.append({'label': label, 'value': display})
    return rows


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
