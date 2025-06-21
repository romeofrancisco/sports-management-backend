from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path("ws/games/<int:game_id>/", consumers.GameScoreConsumer.as_asgi()),
]
