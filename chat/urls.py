from django.urls import path
from .views import TeamChatListView, TeamChatMessagesView, mark_messages_as_read

app_name = 'chat'

urlpatterns = [
    path('teams/', TeamChatListView.as_view(), name='team-chat-list'),
    path('teams/<int:team_id>/messages/', TeamChatMessagesView.as_view(), name='team-chat-messages'),
    path('teams/<int:team_id>/mark-read/', mark_messages_as_read, name='mark-messages-read'),
]
