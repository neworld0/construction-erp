from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import DailyProgressViewSet, PlanChangeRequestViewSet, ProgressSummaryView

router = DefaultRouter()
router.register("daily-progress", DailyProgressViewSet, basename="daily-progress")
router.register("plan-change-requests", PlanChangeRequestViewSet, basename="plan-change-request")

urlpatterns = router.urls
urlpatterns += [
    path("progress/", ProgressSummaryView.as_view()),
    path(
        "plan-change-requests/<int:pk>/submit/",
        PlanChangeRequestViewSet.as_view({"post": "submit"}),
    ),
    path(
        "plan-change-requests/<int:pk>/approve/",
        PlanChangeRequestViewSet.as_view({"post": "approve"}),
    ),
    path(
        "plan-change-requests/<int:pk>/reject/",
        PlanChangeRequestViewSet.as_view({"post": "reject"}),
    ),
]
