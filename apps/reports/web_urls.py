from django.urls import path

from .web_views import (
    report_create,
    report_detail,
    report_edit,
    report_list,
    report_submit,
)

urlpatterns = [
    path("", report_list),
    path("new/", report_create),
    path("<int:report_id>/", report_detail),
    path("<int:report_id>/edit/", report_edit),
    path("<int:report_id>/submit/", report_submit),
]
