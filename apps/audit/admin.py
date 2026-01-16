from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "object_type", "object_id", "actor", "project")
    list_filter = ("action", "object_type", "actor", "project")
    search_fields = ("object_id", "actor__username")
