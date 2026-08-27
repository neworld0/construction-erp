from django.urls import path

from .web_views import hq_plan_change_request_detail, hq_progress_correction_list, hq_progress_correction_review, progress_correction_detail

urlpatterns = [
    path("plan-change-requests/<int:request_id>/", hq_plan_change_request_detail),
    path("progress/corrections/", hq_progress_correction_list),
    path("progress/corrections/<int:correction_id>/", progress_correction_detail),
    path("progress/corrections/<int:correction_id>/review/", hq_progress_correction_review),
]
