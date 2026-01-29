from django.urls import path

from .web_views import hq_contract_change_detail

urlpatterns = [
    path("contract-changes/<int:change_id>/", hq_contract_change_detail),
]
