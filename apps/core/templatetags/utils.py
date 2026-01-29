from django import template


register = template.Library()


@register.filter
def get_attribute(obj, name):
    if obj is None or not name:
        return ""
    return getattr(obj, name, "")


@register.filter
def get_item(mapping, key):
    if not mapping:
        return ""
    return mapping.get(str(key), "")


@register.filter
def work_code(value):
    if value is None:
        return ""
    try:
        return f"{int(value):02d}"
    except (TypeError, ValueError):
        return str(value)
