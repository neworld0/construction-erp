from django.urls import path

from .api_views import ClosingMonthCloseView, ClosingMonthStatusView

urlpatterns = [
    path("month/status/", ClosingMonthStatusView.as_view(), name="closing-status"),
    path("month/close/", ClosingMonthCloseView.as_view(), name="closing-close"),
]
