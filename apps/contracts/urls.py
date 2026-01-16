from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ContractChangeViewSet

router = DefaultRouter()
router.register("contract-changes", ContractChangeViewSet, basename="contract-change")

urlpatterns = router.urls
urlpatterns += [
    path(
        "contract-changes/<int:pk>/submit/",
        ContractChangeViewSet.as_view({"post": "submit"}),
    ),
    path(
        "contract-changes/<int:pk>/approve/",
        ContractChangeViewSet.as_view({"post": "approve"}),
    ),
    path(
        "contract-changes/<int:pk>/reject/",
        ContractChangeViewSet.as_view({"post": "reject"}),
    ),
]
