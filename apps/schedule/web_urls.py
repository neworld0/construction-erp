from django.urls import path

from .web_views import hq_plan_change_request_detail

urlpatterns = [
    path("plan-change-requests/<int:request_id>/", hq_plan_change_request_detail),
]
