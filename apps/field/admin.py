from django.contrib import admin

from .models import DailyReport, DailyReportLine


class DailyReportLineInline(admin.TabularInline):
    model = DailyReportLine
    extra = 0


@admin.register(DailyReport)
class DailyReportAdmin(admin.ModelAdmin):
    list_display = ("project", "report_date", "reporter", "status", "updated_at")
    inlines = [DailyReportLineInline]
