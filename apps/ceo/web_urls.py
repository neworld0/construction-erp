from django.urls import path

from .web_views import dashboard_page, project_detail_page

urlpatterns = [
    path("ceo/dashboard/", dashboard_page, name="ceo-dashboard"),
    path("ceo/projects/<int:project_id>/", project_detail_page, name="ceo-project-detail"),
]
