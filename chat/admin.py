from django.contrib import admin
from .models import TeamChat, ChatMessage

@admin.register(TeamChat)
class TeamChatAdmin(admin.ModelAdmin):
    list_display = ['team', 'created_at']
    list_filter = ['created_at', 'team__sport']
    search_fields = ['team__name']
    readonly_fields = ['created_at']

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ['team_chat', 'sender', 'message_preview', 'timestamp', 'is_read']
    list_filter = ['timestamp', 'is_read', 'team_chat__team__sport']
    search_fields = ['sender__first_name', 'sender__last_name', 'message', 'team_chat__team__name']
    readonly_fields = ['timestamp']
    
    def message_preview(self, obj):
        return obj.message[:50] + "..." if len(obj.message) > 50 else obj.message
    message_preview.short_description = "Message Preview"
