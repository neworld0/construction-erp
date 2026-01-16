from django.contrib import admin

from .models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "client_name",
        "status",
        "is_active",
        "start_date",
        "end_date",
    )
    list_filter = ("status", "is_active")
    search_fields = ("code", "name", "client_name")
