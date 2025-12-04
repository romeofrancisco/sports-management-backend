from django.contrib import admin
from .models import Team, AcademicInfo, PlayerRegistration, PlayerRegistrationDocument

# Register your models here.
@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'abbreviation', 'sport', 'division', 'head_coach', 'assistant_coach')
    search_fields = ('name', 'abbreviation', 'sport__name', 'head_coach__user__email', 'assistant_coach__user__email')
    list_filter = ('sport', 'division')

@admin.register(AcademicInfo)
class AcademicInfoAdmin(admin.ModelAdmin):
    list_display = ('year_level', 'course', 'section')
    search_fields = ('year_level', 'course', 'section')
    list_filter = ('year_level', 'course')


class PlayerRegistrationDocumentInline(admin.TabularInline):
    model = PlayerRegistrationDocument
    extra = 0
    readonly_fields = ('uploaded_at', 'file_extension', 'synced_document')


@admin.register(PlayerRegistration)
class PlayerRegistrationAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_name', 'last_name', 'sport', 'status', 'created_at', 'reviewed_by')
    search_fields = ('email', 'first_name', 'last_name', 'sport__name')
    list_filter = ('status', 'sport', 'created_at')
    readonly_fields = ('created_at', 'updated_at', 'reviewed_at', 'approved_player')
    inlines = [PlayerRegistrationDocumentInline]
    
    fieldsets = (
        ('Personal Information', {
            'fields': ('email', 'first_name', 'last_name', 'sex', 'date_of_birth', 'phone_number')
        }),
        ('Player Information', {
            'fields': ('height', 'weight', 'sport', 'position', 'academic_info')
        }),
        ('Registration Status', {
            'fields': ('status', 'team', 'jersey_number', 'rejection_reason')
        }),
        ('Review Information', {
            'fields': ('reviewed_by', 'reviewed_at', 'approved_player')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(PlayerRegistrationDocument)
class PlayerRegistrationDocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'document_type', 'registration', 'uploaded_at', 'synced_document')
    search_fields = ('title', 'registration__email', 'registration__first_name', 'registration__last_name')
    list_filter = ('document_type', 'uploaded_at')
    readonly_fields = ('uploaded_at', 'file_extension', 'synced_document')
