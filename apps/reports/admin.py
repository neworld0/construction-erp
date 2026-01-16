from django.contrib import admin

from .models import FieldReport, FieldReportFile


class FieldReportFileInline(admin.TabularInline):
    model = FieldReportFile
    extra = 0


@admin.register(FieldReport)
class FieldReportAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "report_date", "status", "created_by")
    list_filter = ("status", "project")
    search_fields = ("title", "content")
    inlines = [FieldReportFileInline]
