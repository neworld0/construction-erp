from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AccrualCostView, CostActualViewSet, CostItemViewSet

router = DefaultRouter()
router.register("cost-items", CostItemViewSet, basename="cost-item")
router.register("cost-actuals", CostActualViewSet, basename="cost-actual")

cost_actual_from_daily_report = CostActualViewSet.as_view({"post": "from_daily_report"})
cost_actual_approve = CostActualViewSet.as_view({"post": "approve"})
cost_actual_close = CostActualViewSet.as_view({"post": "close"})

urlpatterns = [
    path("accrual-cost/", AccrualCostView.as_view()),
    path("cost-actuals/from-daily-report/", cost_actual_from_daily_report),
    path("cost-actuals/<int:pk>/approve/", cost_actual_approve),
    path("cost-actuals/<int:pk>/close/", cost_actual_close),
]
urlpatterns += router.urls
