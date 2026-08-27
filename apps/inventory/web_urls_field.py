from django.urls import path

from .web_views import field_inventory_issue_detail, field_inventory_issue_form, field_inventory_issue_options, field_project_material_requests, field_warehouse_list, field_warehouse_stock

urlpatterns = [
    path("warehouses/", field_warehouse_list),
    path("warehouses/<int:warehouse_id>/stock/", field_warehouse_stock),
    path("issues/", field_inventory_issue_form),
    path("issues/<int:issue_id>/", field_inventory_issue_detail),
    path("issues/options/", field_inventory_issue_options),
    path("item-requests/", field_project_material_requests),
]
