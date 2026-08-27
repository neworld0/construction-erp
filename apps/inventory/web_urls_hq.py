from django.urls import path

from .web_views import hq_project_material_request_review, hq_project_material_requests, hq_warehouse_detail, hq_warehouse_list

urlpatterns = [
    path("warehouses/", hq_warehouse_list),
    path("warehouses/<int:warehouse_id>/", hq_warehouse_detail),
    path("material-requests/", hq_project_material_requests),
    path("material-requests/<int:request_id>/review/", hq_project_material_request_review),
]
