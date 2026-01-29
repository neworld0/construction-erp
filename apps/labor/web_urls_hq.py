from django.urls import path

from .web_views import (
    hq_payroll_detail,
    hq_payroll_list,
    hq_payroll_new,
    hq_timesheet_approve,
    hq_timesheet_detail,
    hq_timesheet_list,
    hq_timesheet_reject,
)

urlpatterns = [
    path("timesheets/", hq_timesheet_list),
    path("timesheets/<int:timesheet_id>/", hq_timesheet_detail),
    path("timesheets/<int:timesheet_id>/approve/", hq_timesheet_approve),
    path("timesheets/<int:timesheet_id>/reject/", hq_timesheet_reject),
    path("payroll/", hq_payroll_list),
    path("payroll/new/", hq_payroll_new),
    path("payroll/<int:batch_id>/", hq_payroll_detail),
]
