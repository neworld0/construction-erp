from django.contrib import admin

from .models import DailyProgress, SchedulePlan, ScheduleTask


class ScheduleTaskInline(admin.TabularInline):
    model = ScheduleTask
    extra = 0


@admin.register(SchedulePlan)
class SchedulePlanAdmin(admin.ModelAdmin):
    list_display = ("project", "version_no", "name", "is_active", "created_at", "updated_at")
    inlines = [ScheduleTaskInline]


@admin.register(DailyProgress)
class DailyProgressAdmin(admin.ModelAdmin):
    list_display = ("project", "task", "report_date", "progress_percent", "reporter")
