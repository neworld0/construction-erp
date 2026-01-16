from django import template

register = template.Library()


@register.simple_tag
def admin_change_url(obj):
    if obj is None:
        return ""
    opts = obj._meta
    return f"/admin/{opts.app_label}/{opts.model_name}/{obj.pk}/change/"
