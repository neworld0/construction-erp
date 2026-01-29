from django.urls import path

from .api_views import PortfolioKPIView, ProjectKPIView, ProjectKPITimelineView

urlpatterns = [
    path("project/<int:project_id>/", ProjectKPIView.as_view()),
    path("projects/<int:project_id>/timeline/", ProjectKPITimelineView.as_view()),
    path("portfolio/", PortfolioKPIView.as_view()),
]
