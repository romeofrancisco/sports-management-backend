from django.contrib import admin
from .models import Tournament


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = ['name', 'sport', 'division', 'status', 'start_date', 'end_date']
    list_filter = ['status', 'division', 'sport', 'start_date']
    search_fields = ['name', 'sport__name']
    filter_horizontal = ['teams']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'sport', 'division', 'logo')
        }),
        ('Tournament Details', {
            'fields': ('status', 'is_recorded')
        }),
        ('Schedule', {
            'fields': ('start_date', 'end_date')
        }),
        ('Teams', {
            'fields': ('teams',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

