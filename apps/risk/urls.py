from django.urls import path

from .views import RiskFindingAckView, RiskFindingDetailView, RiskFindingListView

urlpatterns = [
    path("risk/findings/", RiskFindingListView.as_view()),
    path("risk/findings/<int:pk>/", RiskFindingDetailView.as_view()),
    path("risk/findings/<int:pk>/ack/", RiskFindingAckView.as_view()),
]
