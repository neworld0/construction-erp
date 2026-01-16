from django.urls import path

from .views import (
    ERPLoginView,
    ApprovalApproveView,
    ApprovalRejectView,
    ApprovalRequestListView,
    ApprovalSubmitView,
    health_view,
    logout_view,
)

urlpatterns = [
    path("login/", ERPLoginView.as_view()),
    path("logout/", logout_view),
    path("health", health_view),
    path("api/approvals/", ApprovalRequestListView.as_view()),
    path("api/approvals/submit/", ApprovalSubmitView.as_view()),
    path("api/approvals/<int:pk>/approve/", ApprovalApproveView.as_view()),
    path("api/approvals/<int:pk>/reject/", ApprovalRejectView.as_view()),
]
