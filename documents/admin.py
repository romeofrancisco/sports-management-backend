from django.contrib import admin
from .models import Folder, Document, DocumentPermission


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ['name', 'folder_type', 'parent', 'owner', 'created_at']
    list_filter = ['folder_type', 'created_at']
    search_fields = ['name', 'owner__email', 'owner__first_name', 'owner__last_name']
    raw_id_fields = ['parent', 'owner']
    readonly_fields = ['created_at']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(owner=request.user)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'folder', 'owner', 'uploaded_by', 'status', 'uploaded_at']
    list_filter = ['status', 'uploaded_at', 'folder__folder_type']
    search_fields = ['title', 'description', 'owner__email', 'uploaded_by__email']
    raw_id_fields = ['folder', 'uploaded_by', 'owner', 'original_document']
    readonly_fields = ['uploaded_at', 'updated_at']
    
    fieldsets = (
        ('Document Info', {
            'fields': ('title', 'description', 'file')
        }),
        ('Location & Ownership', {
            'fields': ('folder', 'owner', 'uploaded_by')
        }),
        ('Status', {
            'fields': ('status', 'original_document')
        }),
        ('Timestamps', {
            'fields': ('uploaded_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(owner=request.user)


@admin.register(DocumentPermission)
class DocumentPermissionAdmin(admin.ModelAdmin):
    list_display = ['document', 'user', 'can_view', 'can_edit', 'can_delete', 'granted_by', 'granted_at']
    list_filter = ['can_view', 'can_edit', 'can_delete', 'granted_at']
    search_fields = ['document__title', 'user__email', 'granted_by__email']
    raw_id_fields = ['document', 'user', 'granted_by']
    readonly_fields = ['granted_at']

