from django.urls import path

from .api_views import (
    LaborRateApplicableView,
    LaborRateDetailView,
    LaborRateListView,
    LaborRoleDetailView,
    LaborRoleListView,
    TimesheetApproveView,
    TimesheetDetailView,
    TimesheetLinesView,
    TimesheetListView,
    TimesheetRejectView,
    TimesheetSubmitView,
    PayrollBatchDetailView,
    PayrollBatchLinesView,
    PayrollBatchListView,
    PayrollBatchSubmitView,
)

urlpatterns = [
    path("roles/", LaborRoleListView.as_view()),
    path("roles/<int:role_id>/", LaborRoleDetailView.as_view()),
    path("rates/", LaborRateListView.as_view()),
    path("rates/<int:rate_id>/", LaborRateDetailView.as_view()),
    path("rates/applicable/", LaborRateApplicableView.as_view()),
    path("timesheets/", TimesheetListView.as_view()),
    path("timesheets/<int:timesheet_id>/", TimesheetDetailView.as_view()),
    path("timesheets/<int:timesheet_id>/lines/", TimesheetLinesView.as_view()),
    path("timesheets/<int:timesheet_id>/submit/", TimesheetSubmitView.as_view()),
    path("timesheets/<int:timesheet_id>/approve/", TimesheetApproveView.as_view()),
    path("timesheets/<int:timesheet_id>/reject/", TimesheetRejectView.as_view()),
    path("payroll-batches/", PayrollBatchListView.as_view()),
    path("payroll-batches/<int:batch_id>/", PayrollBatchDetailView.as_view()),
    path("payroll-batches/<int:batch_id>/lines/", PayrollBatchLinesView.as_view()),
    path("payroll-batches/<int:batch_id>/submit/", PayrollBatchSubmitView.as_view()),
]
