from django.urls import path

from .api_views import (
    InventoryLedgerView,
    InventoryStockView,
    ItemDetailView,
    ItemListView,
    IssueDetailView,
    IssueListView,
    IssueSubmitView,
    LocationCreateView,
    TransferActionView,
    TransferListView,
    WarehouseListView,
    WarehouseLocationsView,
)

urlpatterns = [
    path("warehouses/", WarehouseListView.as_view()),
    path("warehouses/<int:warehouse_id>/locations/", WarehouseLocationsView.as_view()),
    path("locations/", LocationCreateView.as_view()),
    path("items/", ItemListView.as_view()),
    path("items/<int:item_id>/", ItemDetailView.as_view()),
    path("ledger/", InventoryLedgerView.as_view()),
    path("stock/", InventoryStockView.as_view()),
    path("transfers/", TransferListView.as_view()),
    path("transfers/<int:transfer_id>/<str:action>/", TransferActionView.as_view()),
    path("issues/", IssueListView.as_view()),
    path("issues/<int:issue_id>/", IssueDetailView.as_view()),
    path("issues/<int:issue_id>/submit/", IssueSubmitView.as_view()),
]
