from rest_framework import viewsets
from .models import Game, PlayerStat
from .serializers import PlayerStatSerializer, GameSerializer, GameActionSerializer
from rest_framework.decorators import action
from sports_management.permissions import IsAdminOrCoachUser
from django.utils import timezone 
from rest_framework.response import Response
from rest_framework import status

class PlayerStatViewSet(viewsets.ModelViewSet):
    serializer_class = PlayerStatSerializer
    permission_classes = [IsAdminOrCoachUser]

    def get_queryset(self):
        return PlayerStat.objects.select_related(
            'player__user',
            'game',
            'stat_type'
        ).filter(
            game__date__lte=timezone.now()
        ).order_by('-timestamp')

    def perform_create(self, serializer):
        # Automatically set period from current game state
        game = serializer.validated_data['game']
        serializer.save(period=game.current_period)

    def filter_queryset(self, queryset):
        # Allow filtering by game/player/period
        queryset = super().filter_queryset(queryset)
        params = self.request.query_params

        if 'game' in params:
            queryset = queryset.filter(game=params['game'])
        if 'player' in params:
            queryset = queryset.filter(player=params['player'])
        if 'period' in params:
            queryset = queryset.filter(period=params['period'])

        return queryset

class GameViewSet(viewsets.ModelViewSet):
    queryset = Game.objects.select_related('sport', 'home_team', 'away_team')
    serializer_class = GameSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        # Add filters if needed
        return queryset

    @action(detail=True, methods=['post'])
    def manage(self, request, pk=None):
        game = self.get_object()
        serializer = GameActionSerializer(
            data=request.data,
            context={'game': game}  # Pass game instance to serializer
        )
        serializer.is_valid(raise_exception=True)
        
        action = serializer.validated_data['action']
        notes = serializer.validated_data.get('notes', '')
        
        try:
            if action == 'start':
                game.start_game(notes=notes)
            elif action == 'complete':
                game.complete_game(notes=notes)
            elif action == 'postpone':
                game.postpone_game(notes=notes)
                
            return Response(
                GameSerializer(game, context={'request': request}).data,
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def update_scores(self, request, pk=None):
        game = self.get_object()
        game.update_scores()
        return Response(
            GameSerializer(game, context={'request': request}).data,
            status=status.HTTP_200_OK
        )