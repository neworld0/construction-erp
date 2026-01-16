from django.contrib import admin

from .models import ContactMessage, PublicProject


@admin.register(PublicProject)
class PublicProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "is_published", "year")
    list_filter = ("category", "is_published")
    search_fields = ("title", "location", "client")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "created_at")
    search_fields = ("name", "email", "phone")
