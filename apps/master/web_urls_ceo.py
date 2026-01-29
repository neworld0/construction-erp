from django.urls import path

from .web_views import (
    ceo_cbs_list_view,
    ceo_cbs_request_approve,
    ceo_cbs_request_detail,
    ceo_cbs_request_reject,
    ceo_cbs_requests_list,
)

urlpatterns = [
    path("", ceo_cbs_list_view),
    path("requests/", ceo_cbs_requests_list),
    path("requests/<int:pk>/", ceo_cbs_request_detail),
    path("requests/<int:pk>/approve/", ceo_cbs_request_approve),
    path("requests/<int:pk>/reject/", ceo_cbs_request_reject),
]
