from django.urls import path

from .web_views import (
    field_approved_list,
    field_cost_detail,
    field_cost_edit,
    field_dashboard,
    field_progress_detail,
    field_progress_edit,
    field_progress_yesterday,
    field_wbs_change_new,
)
from .mobile_views import (
    field_mobile_costs,
    field_mobile_home,
    field_mobile_inventory_issue,
    field_mobile_progress,
    field_mobile_reports,
    field_mobile_timesheet,
)
from apps.closing.web_views import field_adjustment_detail, field_adjustment_new

urlpatterns = [
    path("", field_dashboard),
    path("approved/", field_approved_list),
    path("mobile/", field_mobile_home),
    path("mobile/progress/", field_mobile_progress),
    path("mobile/reports/", field_mobile_reports),
    path("mobile/costs/", field_mobile_costs),
    path("mobile/inventory/issue", field_mobile_inventory_issue),
    path("mobile/labor/timesheet", field_mobile_timesheet),
    path("cost/<int:cost_actual_id>/", field_cost_detail),
    path("cost/<int:cost_actual_id>/edit/", field_cost_edit),
    path("progress/<int:progress_id>/", field_progress_detail),
    path("progress/<int:progress_id>/edit/", field_progress_edit),
    path("progress/yesterday/", field_progress_yesterday),
    path("adjustments/new/", field_adjustment_new),
    path("adjustments/<int:adjustment_id>/", field_adjustment_detail),
    path("projects/<int:project_id>/wbs-change/new/", field_wbs_change_new),
]
