from django.contrib import admin

from .models import Evidence, EvidenceFile, EvidencePolicy


class EvidenceFileInline(admin.TabularInline):
    model = EvidenceFile
    extra = 0


@admin.register(Evidence)
class EvidenceAdmin(admin.ModelAdmin):
    list_display = ("object_type", "object_id", "title", "created_by", "created_at")
    inlines = [EvidenceFileInline]


@admin.register(EvidencePolicy)
class EvidencePolicyAdmin(admin.ModelAdmin):
    list_display = ("object_type", "when_status", "is_required", "min_files")
