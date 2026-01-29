from django.urls import path

from .web_views import field_timesheet_form, field_timesheet_list

urlpatterns = [
    path("timesheets/", field_timesheet_list),
    path("timesheets/new/", field_timesheet_form),
    path("timesheets/<int:timesheet_id>/", field_timesheet_form),
]
