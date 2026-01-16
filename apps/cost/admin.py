from django.contrib import admin

from .models import CostActual, CostActualLine, CostItem, RevenueRecognition


@admin.register(CostItem)
class CostItemAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "category",
        "unit",
        "is_direct",
        "is_active",
        "sort_order",
    )
    list_filter = ("category", "is_direct", "is_active")
    search_fields = ("code", "name")


class CostActualLineInline(admin.TabularInline):
    model = CostActualLine
    extra = 0


@admin.register(CostActual)
class CostActualAdmin(admin.ModelAdmin):
    list_display = ("project", "report_date", "status", "total_amount", "approved_at", "closed_at")
    inlines = [CostActualLineInline]


@admin.register(RevenueRecognition)
class RevenueRecognitionAdmin(admin.ModelAdmin):
    list_display = ("project", "as_of_date", "progress_percent", "recognized_revenue", "delta_revenue")
