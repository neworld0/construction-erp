from .site_config import SITE_INFO


def public_site_context(_request):
    return SITE_INFO.copy()
