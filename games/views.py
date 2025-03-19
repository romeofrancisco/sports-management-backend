from rest_framework import viewsets
from sports.models import SportStatType
from .models import Game, PlayerStat
from .serializers import PlayerStatSerializer, GameSerializer

class PlayerStatViewSet(viewsets.ModelViewSet):
    queryset = PlayerStat.objects.all()
    serializer_class = PlayerStatSerializer

class GameViewSet(viewsets.ModelViewSet):
    queryset = Game.objects.all()
    serializer_class = GameSerializer