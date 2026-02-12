from django.urls import include, path

from apps.evidence.web_views import evidence_edit
from apps.contracts import web_urls as contract_web_urls
from apps.schedule import web_urls as schedule_web_urls
from apps.projects.hq_views import (
    hq_project_detail,
    hq_project_list,
    hq_project_new,
    hq_wbs_change_new,
)
from apps.projects.approval_package_views import (
    hq_approval_package_detail,
    hq_approval_package_list,
    hq_approval_package_new,
    hq_approval_package_submit,
)
from apps.closing.web_views import (
    hq_adjustment_detail,
    hq_adjustment_list,
    hq_adjustment_submit,
    hq_closing_detail,
    hq_closing_list,
    hq_closing_new,
    hq_closing_submit,
    ceo_closing_approve,
    ceo_closing_reject,
)
from .views import (
    app_entry,
    hq_app_view,
    hq_inbox_view,
    hq_risk_list_view,
    hq_missing_list_view,
    hq_daily_report_detail,
    hq_daily_progress_detail,
    hq_field_report_detail,
    hq_cost_actual_detail,
    hq_approval_detail,
    evidence_file_open,
)

urlpatterns = [
    path("", app_entry),
    path("ceo/", include("apps.ceo.app_urls")),
    path("hq/master/", include("apps.master.web_urls")),
    path("hq/master/", include("apps.labor.web_urls")),
    path("hq/", hq_app_view),
    path("hq/inbox/", hq_inbox_view),
    path("hq/risks/", hq_risk_list_view),
    path("hq/missing/", hq_missing_list_view),
    path("hq/reports/<int:report_id>/", hq_daily_report_detail),
    path("hq/progress/<int:progress_id>/", hq_daily_progress_detail),
    path("hq/field-reports/<int:field_report_id>/", hq_field_report_detail),
    path("hq/costs/<int:cost_actual_id>/", hq_cost_actual_detail),
    path("hq/approvals/<int:approval_id>/", hq_approval_detail),
    path("hq/", include(contract_web_urls)),
    path("hq/", include(schedule_web_urls)),
    path("hq/projects/", hq_project_list),
    path("hq/projects/new/", hq_project_new),
    path("hq/projects/<int:project_id>/", hq_project_detail),
    path("hq/projects/<int:project_id>/wbs-change/new/", hq_wbs_change_new),
    path(
        "hq/projects/<int:project_id>/approval-packages/",
        hq_approval_package_list,
    ),
    path("hq/projects/<int:project_id>/approval-packages/new/", hq_approval_package_new),
    path(
        "hq/projects/<int:project_id>/approval-packages/<int:package_id>/",
        hq_approval_package_detail,
    ),
    path(
        "hq/approval-packages/<int:package_id>/submit/",
        hq_approval_package_submit,
    ),
    path("hq/adjustments/", hq_adjustment_list),
    path("hq/adjustments/<int:adjustment_id>/", hq_adjustment_detail),
    path("hq/adjustments/<int:adjustment_id>/submit/", hq_adjustment_submit),
    path("hq/closing/", hq_closing_list),
    path("hq/closing/new/", hq_closing_new),
    path("hq/closing/<int:closing_id>/", hq_closing_detail),
    path("hq/closing/<int:closing_id>/submit/", hq_closing_submit),
    path("hq/closing/<int:closing_id>/approve/", ceo_closing_approve),
    path("hq/closing/<int:closing_id>/reject/", ceo_closing_reject),
    path("hq/inventory/", include("apps.inventory.web_urls_hq")),
    path("hq/labor/", include("apps.labor.web_urls_hq")),
    path("field/", include("apps.field.web_urls")),
    path("field/inventory/", include("apps.inventory.web_urls_field")),
    path("field/labor/", include("apps.labor.web_urls_field")),
    path("reports/", include("apps.reports.web_urls")),
    path("evidence/<int:pk>/edit/", evidence_edit),
    path("evidence-files/<int:file_id>/open/", evidence_file_open, name="evidence-file-open"),
]
