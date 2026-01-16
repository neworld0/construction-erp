from django.urls import path

from apps.cost.views import RevenueRecognitionView
from apps.finance.views import CashEventCreateView, CashSummaryView, ProfitLossView

urlpatterns = [
    path("revenue-recognition/", RevenueRecognitionView.as_view()),
    path("profit-loss/", ProfitLossView.as_view()),
    path("cash/summary/", CashSummaryView.as_view()),
    path("cash/events/", CashEventCreateView.as_view()),
]
