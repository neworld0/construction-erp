from django.urls import path

from .web_views import (
    field_cost_edit,
    field_dashboard,
    field_progress_edit,
    field_wbs_change_new,
)
from apps.closing.web_views import field_adjustment_detail, field_adjustment_new

urlpatterns = [
    path("", field_dashboard),
    path("cost/<int:cost_actual_id>/edit/", field_cost_edit),
    path("progress/<int:progress_id>/edit/", field_progress_edit),
    path("adjustments/new/", field_adjustment_new),
    path("adjustments/<int:adjustment_id>/", field_adjustment_detail),
    path("projects/<int:project_id>/wbs-change/new/", field_wbs_change_new),
]
