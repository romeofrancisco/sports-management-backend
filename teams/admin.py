from django.contrib import admin
from .models import Team

# Register your models here.
@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'abbreviation', 'sport', 'division', 'head_coach', 'assistant_coach')
    search_fields = ('name', 'abbreviation', 'sport__name', 'head_coach__user__email', 'assistant_coach__user__email')
    list_filter = ('sport', 'division')
