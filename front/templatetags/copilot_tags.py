import json

from django import template
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html

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


EMPTY_DISPLAY = '(vide)'
NO_ENTITY_DISPLAY = '(aucun)'


def _arg_label(key):
    if key in _UUID_FIELDS:
        return _UUID_FIELDS[key][0]
    return _ARG_LABELS.get(key, key)


def _entity_url(key, value):
    """Public page of a resolved *_uuid arg, or None when it has none.

    Only websites: they are the sole registry entity with a public page keyed by their own uuid
    (`/paroisse/<uuid>`). A malformed uuid can't reach here (the DB lookup filtered it out), but
    guard anyway — a broken reverse in a template filter would blank the whole discussion.
    """
    if key != 'website_uuid':
        return None
    try:
        return reverse('website_view', kwargs={'website_uuid': value})
    except NoReverseMatch:
        return None


def _linked(label, url):
    """`format_html` escapes the label; the icon markup stays raw, as intended."""
    return format_html(
        '<a class="copilot-entity-link" href="{}" target="_blank" rel="noopener">{}'
        '<i class="fas fa-up-right-from-square"></i></a>', url, label)


def _display_value(key, value):
    """Render one arg value. Shared by the old and the new value so both read identically."""
    if value is None or value == '':
        return NO_ENTITY_DISPLAY if key in _UUID_FIELDS else EMPTY_DISPLAY
    if key in _UUID_FIELDS:
        model = _UUID_FIELDS[key][1]
        try:
            name = model.objects.filter(uuid=value).values_list('name', flat=True).first()
        except (ValueError, ValidationError, TypeError):
            name = None
        if not name:
            return f'{value} (introuvable)'
        url = _entity_url(key, value)
        return _linked(name, url) if url else name
    if isinstance(value, bool):
        return 'Oui' if value else 'Non'
    if key in ('latitude', 'longitude') and isinstance(value, (int, float)):
        # ~11 cm. Both sides go through the same formatting, so a no-op move reads as unchanged.
        return f'{value:.6f}'.rstrip('0').rstrip('.') or '0'
    return value


def _is_unchanged(key, old_value, new_value, old_display, new_display):
    """Whether the proposed value is the one already in DB (so no `ancien → nouveau` is shown).

    Compares the DISPLAYED strings, which harmonizes '' vs None and float precision. UUID keys are
    the exception: two distinct entities can share a name, so they compare on the raw uuid — an
    actual FK change must never be hidden behind an identical label.
    """
    if key in _UUID_FIELDS:
        return old_value == new_value
    return old_display == new_display


@register.filter
def humanize_tool_call(tool_args, tool_args_before=None):
    """Turn a proposed tool's raw args into readable rows for the approval card.

    Every *_uuid is resolved to its entity name so the human validator can read and understand the
    action instead of an opaque UUID. Unknown keys fall back to the raw key/value.

    Returns {'rows', 'snapshot_rows'}:
    - `rows` are the args the agent sent; when tool_args_before (a deterministic snapshot taken in
      Python at proposal time, never by the LLM) holds that key, the row also carries the old
      display value so the template can render `ancien → nouveau`.
    - `snapshot_rows` are the keys present only in the snapshot — the "Valeurs actuelles" block of
      a delete_*, whose args carry nothing but the target uuid.
    """
    if not isinstance(tool_args, dict):
        return {'rows': [], 'snapshot_rows': []}
    before = tool_args_before if isinstance(tool_args_before, dict) else {}

    rows = []
    for key, value in tool_args.items():
        if value is None:
            continue
        row = {'label': _arg_label(key), 'value': _display_value(key, value)}
        # `key in before` and not `before.get(key)`: a NULL old value is meaningful, it is what
        # makes `(vide) → 12 rue des Clefs` possible.
        if key in before:
            row['old_value'] = _display_value(key, before[key])
            row['has_change'] = not _is_unchanged(key, before[key], value,
                                                  row['old_value'], row['value'])
        rows.append(row)

    snapshot_rows = [{'label': _arg_label(key), 'value': _display_value(key, value)}
                     for key, value in before.items() if key not in tool_args]
    return {'rows': rows, 'snapshot_rows': snapshot_rows}


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
