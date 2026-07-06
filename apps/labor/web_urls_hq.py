from django.urls import path
from django.views.generic import RedirectView

from .web_views import (
    hq_e_card_import_batch_list,
    hq_e_card_import_batch_detail,
    hq_labor_excel_export_download,
    hq_confirmed_work_day_list,
    hq_labor_reporting_map,
    hq_labor_work_ledger_form,
    hq_labor_work_ledger_list,
    hq_payroll_allocation_list,
    hq_payroll_detail,
    hq_payroll_list,
    hq_payroll_new,
    hq_timesheet_approve,
    hq_timesheet_detail,
    hq_timesheet_list,
    hq_timesheet_reject,
    hq_worker_master_edit,
    hq_worker_master_delete,
    hq_worker_master_list,
    hq_worker_master_new,
)

urlpatterns = [
    path("e-card-imports/", hq_e_card_import_batch_list),
    path("e-card-imports/<int:batch_id>/", hq_e_card_import_batch_detail),
    path("excel-exports/<int:export_id>/download/", hq_labor_excel_export_download),
    path("confirmed-work-days/", hq_confirmed_work_day_list),
    path("workers/", hq_worker_master_list),
    path("workers/new/", hq_worker_master_new),
    path("workers/<int:worker_id>/edit/", hq_worker_master_edit),
    path("workers/<int:worker_id>/delete/", hq_worker_master_delete),
    path("work-ledger/", hq_labor_work_ledger_list),
    path("work-ledger/new/", hq_labor_work_ledger_form),
    path("work-ledger/<int:ledger_id>/", hq_labor_work_ledger_form),
    path("reporting-map/", hq_labor_reporting_map),
    path("timesheets/", hq_timesheet_list),
    path("timesheets/<int:timesheet_id>/", hq_timesheet_detail),
    path("timesheets/<int:timesheet_id>/approve/", hq_timesheet_approve),
    path("timesheets/<int:timesheet_id>/reject/", hq_timesheet_reject),
    path("monthly-payroll/", hq_payroll_list),
    path("payroll-allocation/", hq_payroll_allocation_list),
    path("payroll-allocation/new/", hq_payroll_new),
    path("payroll-allocation/<int:batch_id>/", hq_payroll_detail),
    path(
        "payroll/",
        RedirectView.as_view(url="/app/hq/labor/payroll-allocation/", permanent=False),
    ),
    path(
        "payroll/new/",
        RedirectView.as_view(
            url="/app/hq/labor/payroll-allocation/new/", permanent=False
        ),
    ),
    path(
        "payroll/<int:batch_id>/",
        RedirectView.as_view(
            url="/app/hq/labor/payroll-allocation/%(batch_id)s/", permanent=False
        ),
    ),
]
