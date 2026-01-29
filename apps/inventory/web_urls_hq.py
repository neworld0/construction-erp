from django.urls import path

from .web_views import hq_warehouse_detail, hq_warehouse_list

urlpatterns = [
    path("warehouses/", hq_warehouse_list),
    path("warehouses/<int:warehouse_id>/", hq_warehouse_detail),
]
