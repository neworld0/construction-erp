from django.contrib import admin

from .models import ApprovalRequest
from .rbac.models import ProjectAssignment, UserProfile


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("object_type", "object_id", "status", "submitted_at", "approved_at")
    list_filter = ("object_type", "status")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role")
    list_filter = ("role",)
    search_fields = ("user__username", "user__email")


@admin.register(ProjectAssignment)
class ProjectAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "project", "is_active")
    list_filter = ("project", "user", "is_active")
    search_fields = ("user__username", "project__name", "project__code")
