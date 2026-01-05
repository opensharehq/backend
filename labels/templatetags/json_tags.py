"""JSON template filters for labels."""

import json

from django import template

register = template.Library()


@register.filter(name="pretty_json")
def pretty_json(value):
    """Format a dict or JSON string as pretty-printed JSON."""
    if value is None:
        return "{}"
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)
