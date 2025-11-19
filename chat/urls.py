from django.urls import path
from .views import TeamChatListView, TeamChatMessagesView, mark_messages_as_read, get_vapid_public_key, subscribe_to_push

app_name = 'chat'

urlpatterns = [
    path('teams/', TeamChatListView.as_view(), name='team-chat-list'),
    path('teams/<int:team_id>/messages/', TeamChatMessagesView.as_view(), name='team-chat-messages'),
    path('teams/<int:team_id>/mark-read/', mark_messages_as_read, name='mark-messages-read'),
    path('push/vapid-public-key/', get_vapid_public_key, name='vapid-public-key'),
    path('push/subscribe/', subscribe_to_push, name='subscribe-push'),
]
