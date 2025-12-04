from django.contrib import admin
from .models import FCMDevice, NotificationLog


@admin.register(FCMDevice)
class FCMDeviceAdmin(admin.ModelAdmin):
    list_display = ('user', 'fcm_token', 'created_at', 'updated_at')
    list_filter = ('created_at',)
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'fcm_token')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'notification_type', 'action_type', 'title', 'is_read', 'created_at')
    list_filter = ('notification_type', 'action_type', 'is_read', 'created_at')
    search_fields = ('recipient__email', 'recipient__first_name', 'recipient__last_name', 'title', 'body')
    readonly_fields = ('recipient', 'notification_type', 'action_type', 'title', 'body', 'related_object_id', 'related_object_type', 'click_action', 'created_at')
    ordering = ('-created_at',)
    
    def has_add_permission(self, request):
        return False  # Notifications are created programmatically
    
    def has_change_permission(self, request, obj=None):
        return True  # Allow marking as read
