"""Deterministic snapshot of the values a proposed mutating tool is about to overwrite or delete.

Computed in Python at proposal time and frozen on the item (CopilotDiscussionItem.tool_args_before)
for two reasons: the LLM must never be the source of the "old" value, and once the action is
approved and executed the database holds the NEW value — reading it back at render time would show
old == new for every past item.

Never raises: _finalize() runs OUTSIDE the runner's try/except, so an exception here would leave the
discussion stuck in RUNNING. A display nicety must never break a turn.
"""
from django.core.exceptions import ValidationError

from front.models import CopilotDiscussion
from registry.models import Church, Parish, Website

# An update_* only touches the keys the agent sent, so `fields=None` means "snapshot those" and no
# field list has to be kept in sync with tools.do_update_*. A delete_* carries nothing but the
# target uuid, so it needs an explicit list of the values that are about to be lost.
_CHURCH_FIELDS = ('name', 'city', 'zipcode', 'address', 'latitude', 'longitude', 'parish_uuid',
                  'is_active')
_PARISH_FIELDS = ('name', 'diocese_uuid', 'website_uuid')
_WEBSITE_FIELDS = ('name', 'home_url', 'is_active', 'enabled_for_crawling')

# Proposed tool -> (target model, arg key holding the target uuid, fields to snapshot).
_TARGETS = {
    'update_church': (Church, 'church_uuid', None),
    'update_parish': (Parish, 'parish_uuid', None),
    'update_website': (Website, 'website_uuid', None),
    'delete_church': (Church, 'church_uuid', _CHURCH_FIELDS),
    'delete_parish': (Parish, 'parish_uuid', _PARISH_FIELDS),
    'delete_website': (Website, 'website_uuid', _WEBSITE_FIELDS),
}


def _fk_uuid(instance, attribute: str):
    related = getattr(instance, attribute, None)
    return str(related.uuid) if related is not None else None


# Arg keys that are not a plain attribute of the target -> how to read their current value.
_READERS = {
    'latitude': lambda o: o.location.y if o.location else None,
    'longitude': lambda o: o.location.x if o.location else None,
    'parish_uuid': lambda o: _fk_uuid(o, 'parish'),
    'diocese_uuid': lambda o: _fk_uuid(o, 'diocese'),
    'website_uuid': lambda o: _fk_uuid(o, 'website'),
}


def _scalar(value):
    """JSONField uses the stock json encoder, which raises on a UUID: coerce anything exotic."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _get_instance(model, target_uuid):
    if not target_uuid:
        return None
    try:
        return model.objects.filter(uuid=target_uuid).first()
    except (ValueError, ValidationError, TypeError):
        return None


def _assign_website_before(discussion: CopilotDiscussion) -> dict:
    """assign_website re-points the discussion itself, not a registry entity.

    Read the website afresh: the in-memory discussion was loaded at the start of the run, and on
    the resume path an approved do_assign_website updates it through a queryset, which leaves the
    Python object stale.
    """
    current = (CopilotDiscussion.objects
               .filter(uuid=discussion.uuid)
               .values_list('website__uuid', flat=True)
               .first())
    return {'website_uuid': str(current) if current else None}


def _parsing_before(tool_args: dict) -> dict | None:
    """update_parsing_human_json replaces a whole schedules json, not a set of flat fields.

    The snapshot keeps the effective json (human_json, else llm_json) with its version, so the
    approval card can render the CURRENT schedules next to the proposed ones. It is display-only
    and never enters the agent's context (tool_args_before is excluded from _HISTORY_FIELDS).
    """
    from scheduling.models import Parsing
    from scheduling.public_service import scheduling_get_parsing_dict_and_version

    parsing = _get_instance(Parsing, tool_args.get('parsing_uuid'))
    if parsing is None:
        return None
    schedules_json, version = scheduling_get_parsing_dict_and_version(parsing)
    if schedules_json is None:
        return None

    return {'schedules_list': schedules_json, 'schedules_list_version': version}


def snapshot_before_values(discussion: CopilotDiscussion, tool_name: str,
                           tool_args) -> dict | None:
    """Return {arg_key: current value in DB} for what a proposed tool is about to change.

    The identity key (the target's own uuid) is skipped: it is not modified. Keys whose current
    value is NULL are still reported, so the UI can tell filling an empty field from overwriting
    one. Returns None when there is nothing to show.
    """
    if not isinstance(tool_args, dict):
        return None
    try:
        if tool_name == 'assign_website':
            return _assign_website_before(discussion)
        if tool_name == 'update_parsing_human_json':
            return _parsing_before(tool_args)
        if tool_name not in _TARGETS:
            return None
        model, uuid_key, fields = _TARGETS[tool_name]
        instance = _get_instance(model, tool_args.get(uuid_key))
        if instance is None:
            return None

        keys = fields if fields is not None else [
            key for key, value in tool_args.items() if value is not None]
        before = {}
        for key in keys:
            if key == uuid_key:
                continue
            reader = _READERS.get(key)
            try:
                current = reader(instance) if reader else getattr(instance, key)
            except AttributeError:
                continue
            before[key] = _scalar(current)
        return before or None
    except Exception:  # noqa: BLE001 - never break a turn for a display nicety (see docstring)
        return None
