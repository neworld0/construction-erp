from django.urls import path

from .views import (
    EvidenceDetailView,
    EvidenceFileDownloadView,
    EvidenceFileUploadView,
    EvidenceListCreateView,
)

urlpatterns = [
    path("evidence/", EvidenceListCreateView.as_view()),
    path("evidence/<int:pk>/", EvidenceDetailView.as_view()),
    path("evidence/<int:pk>/files/", EvidenceFileUploadView.as_view()),
    path("evidence-files/<int:pk>/download/", EvidenceFileDownloadView.as_view()),
]
