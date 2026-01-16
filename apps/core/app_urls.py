from django.urls import include, path

from apps.evidence.web_views import evidence_edit
from .views import app_entry, hq_app_view

urlpatterns = [
    path("", app_entry),
    path("ceo/", include("apps.ceo.app_urls")),
    path("hq/", hq_app_view),
    path("field/", include("apps.field.web_urls")),
    path("reports/", include("apps.reports.web_urls")),
    path("evidence/<int:pk>/edit/", evidence_edit),
]
