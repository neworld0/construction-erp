from django.urls import path

from .views import (
    CEODashboardView,
    CEOProjectSummaryReportView,
    CEOProjectSummaryView,
    CEOProjectsView,
)

urlpatterns = [
    path("ceo/dashboard/", CEODashboardView.as_view()),
    path("ceo/projects/", CEOProjectsView.as_view()),
    path("ceo/projects/<int:id>/summary/", CEOProjectSummaryView.as_view()),
    path("ceo/reports/project-summary.csv", CEOProjectSummaryReportView.as_view()),
]
