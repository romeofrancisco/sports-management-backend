from django.contrib import admin
from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "startDate", "endDate", "status")
    list_filter = ("status", "startDate")
    search_fields = ("title", "description", "location")
