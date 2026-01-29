from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ProjectViewSet
from .api_views import ProjectWBSBaselineBadgeView, ProjectWBSBaselineHistoryView

router = DefaultRouter()
router.register("projects", ProjectViewSet, basename="project")

urlpatterns = router.urls + [
    path(
        "projects/<int:project_id>/wbs-baseline/badge/",
        ProjectWBSBaselineBadgeView.as_view(),
    ),
    path(
        "projects/<int:project_id>/wbs-baseline/history/",
        ProjectWBSBaselineHistoryView.as_view(),
    ),
]
