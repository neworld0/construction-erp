from django.urls import path

from .app_views import ceo_home, ceo_projects_list
from .web_views import project_detail_page

urlpatterns = [
    path("", ceo_home),
    path("projects/", ceo_projects_list),
    path("projects/<int:project_id>/", project_detail_page),
]
