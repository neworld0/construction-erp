"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import os
import sys
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path, re_path
from django.views.static import serve
from two_factor import urls as two_factor_urls

from apps.core.views import healthz_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path("", include("apps.core.urls")),
    path("", include("apps.public_site.urls")),
    path(
        "",
        include((two_factor_urls.urlpatterns[0], "two_factor"), namespace="two_factor"),
    ),
    path("healthz/", healthz_view),
    path("", include("apps.ceo.web_urls")),
    path("app/", include("apps.core.app_urls")),
    path("api/", include("apps.projects.urls")),
    path("api/", include("apps.cost.urls")),
    path("api/", include("apps.field.urls")),
    path("api/", include("apps.finance.urls")),
    path("api/", include("apps.schedule.urls")),
    path("api/", include("apps.contracts.urls")),
    path("api/", include("apps.evidence.urls")),
    path("api/", include("apps.risk.urls")),
    path("api/", include("apps.ceo.urls")),
    path("api/", include("apps.audit.urls")),
    path("api/", include("apps.master.api_urls")),
    path("api/closing/", include("apps.closing.urls")),
    path("api/kpi/", include("apps.kpi.urls")),
    path("api/inventory/", include("apps.inventory.urls")),
    path("api/labor/", include("apps.labor.urls")),
]

serve_media = str(os.getenv("DJANGO_SERVE_MEDIA", "")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
is_runserver = any(arg == "runserver" for arg in sys.argv)
is_local_settings = os.getenv("DJANGO_SETTINGS_MODULE") == "config.settings.local"
should_serve_media = settings.DEBUG or is_local_settings or serve_media or is_runserver

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += staticfiles_urlpatterns()
elif is_local_settings:
    urlpatterns += staticfiles_urlpatterns()

if should_serve_media:
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]
