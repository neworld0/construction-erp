from django.urls import path

from .web_views import field_cost_edit, field_dashboard, field_progress_edit

urlpatterns = [
    path("", field_dashboard),
    path("cost/<int:cost_actual_id>/edit/", field_cost_edit),
    path("progress/<int:progress_id>/edit/", field_progress_edit),
]
