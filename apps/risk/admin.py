from django.contrib import admin

from .models import RiskEvent, RiskFinding, RiskRule


@admin.register(RiskRule)
class RiskRuleAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "severity", "is_active", "updated_at")
    list_filter = ("severity", "is_active")
    search_fields = ("key", "name")


@admin.register(RiskEvent)
class RiskEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "object_type", "object_id", "actor", "created_at")
    list_filter = ("event_type",)
    search_fields = ("object_type", "object_id")


@admin.register(RiskFinding)
class RiskFindingAdmin(admin.ModelAdmin):
    list_display = ("title", "severity", "status", "rule", "project", "created_at")
    list_filter = ("status", "severity", "rule")
    search_fields = ("object_id", "title")
