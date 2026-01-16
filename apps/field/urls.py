from rest_framework.routers import DefaultRouter

from .views import DailyReportViewSet

router = DefaultRouter()
router.register("daily-reports", DailyReportViewSet, basename="daily-report")

urlpatterns = router.urls
