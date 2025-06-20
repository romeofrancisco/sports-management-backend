from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/chat/team/(?P<team_id>\d+)/$', consumers.TeamChatConsumer.as_asgi()),
    re_path(r'ws/chat/global/$', consumers.GlobalChatConsumer.as_asgi()),
]
