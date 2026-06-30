import json

from django import template

register = template.Library()


@register.filter
def to_pretty_json(value):
    if value is None:
        return ''
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)
