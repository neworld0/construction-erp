from django.urls import include, path
from django.views.generic import RedirectView
from apps.contracts.web_views import hq_contract_change_detail
from apps.core.views import (
    hq_approval_detail,
    hq_cost_actual_detail,
    hq_daily_progress_detail,
    hq_daily_report_detail,
    hq_field_report_detail,
    hq_inbox_view,
)
from apps.labor.web_views import hq_timesheet_detail
from apps.schedule.web_views import hq_plan_change_request_detail

from .app_views import (
    ceo_approval_quick_approve,
    ceo_approval_quick_reject,
    ceo_home,
    ceo_project_kpi_detail,
    ceo_projects_list,
    ceo_wbs_change_approve,
    ceo_wbs_change_detail,
    ceo_wbs_change_list,
    ceo_wbs_change_reject,
)
from .approval_package_views import (
    ceo_approval_package_approve,
    ceo_approval_package_detail,
    ceo_approval_package_list,
    ceo_approval_package_reject,
)
from apps.closing.web_views import (
    ceo_adjustment_approve,
    ceo_adjustment_detail,
    ceo_adjustment_list,
    ceo_adjustment_reject,
)
from .web_views import project_detail_page

urlpatterns = [
    path("", ceo_home),
    path("inbox/", hq_inbox_view),
    path("approvals/approve/", ceo_approval_quick_approve),
    path("approvals/reject/", ceo_approval_quick_reject),
    path("approvals/<int:approval_id>/", hq_approval_detail),
    path("reports/<int:report_id>/", hq_daily_report_detail),
    path("progress/<int:progress_id>/", hq_daily_progress_detail),
    path("field-reports/<int:field_report_id>/", hq_field_report_detail),
    path("costs/<int:cost_actual_id>/", hq_cost_actual_detail),
    path("contract-changes/<int:change_id>/", hq_contract_change_detail),
    path("plan-change-requests/<int:request_id>/", hq_plan_change_request_detail),
    path("labor/timesheets/<int:timesheet_id>/", hq_timesheet_detail),
    path("cbs/", include("apps.master.web_urls_ceo")),
    path("cbs/cbs/", RedirectView.as_view(url="/app/ceo/cbs/", permanent=True)),
    path("projects/", ceo_projects_list),
    path("projects/<int:project_id>/", project_detail_page),
    path("projects/<int:project_id>/kpi/", ceo_project_kpi_detail),
    path("wbs-change/requests/", ceo_wbs_change_list),
    path("wbs-change/requests/<int:request_id>/", ceo_wbs_change_detail),
    path("wbs-change/requests/<int:request_id>/approve/", ceo_wbs_change_approve),
    path("wbs-change/requests/<int:request_id>/reject/", ceo_wbs_change_reject),
    path("approval-packages/", ceo_approval_package_list),
    path("approval-packages/<int:package_id>/", ceo_approval_package_detail),
    path(
        "approval-packages/<int:package_id>/approve/",
        ceo_approval_package_approve,
    ),
    path(
        "approval-packages/<int:package_id>/reject/",
        ceo_approval_package_reject,
    ),
    path("adjustments/", ceo_adjustment_list),
    path("adjustments/<int:adjustment_id>/", ceo_adjustment_detail),
    path("adjustments/<int:adjustment_id>/approve/", ceo_adjustment_approve),
    path("adjustments/<int:adjustment_id>/reject/", ceo_adjustment_reject),
]
