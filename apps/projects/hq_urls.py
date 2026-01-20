from django.urls import path

from . import hq_views

urlpatterns = [
    path("projects/", hq_views.hq_project_list),
    path("projects/new/", hq_views.hq_project_new),
    path("projects/<int:project_id>/", hq_views.hq_project_detail),
]
