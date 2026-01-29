from django.urls import path

from .web_views import field_inventory_issue_form, field_warehouse_list

urlpatterns = [
    path("warehouses/", field_warehouse_list),
    path("issues/", field_inventory_issue_form),
]
