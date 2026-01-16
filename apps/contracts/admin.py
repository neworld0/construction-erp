from django.contrib import admin

from .models import ContractChange, ContractSnapshot


@admin.register(ContractChange)
class ContractChangeAdmin(admin.ModelAdmin):
    list_display = (
        "project",
        "change_no",
        "change_type",
        "status",
        "contract_amount_delta",
        "time_extension_days",
        "submitted_at",
        "approved_at",
    )
    list_filter = ("change_type", "status")
    search_fields = ("project__name", "project__code")


@admin.register(ContractSnapshot)
class ContractSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "project",
        "version_no",
        "base_contract_amount",
        "is_active",
        "source_change",
        "created_at",
    )
    list_filter = ("is_active",)
    search_fields = ("project__name", "project__code")
