from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from rest_framework.exceptions import ValidationError
from django.db.models import Value, IntegerField
from .models import Game, PlayerStat, Substitution
from teams.models import Player
from sports.models import SportStatType
from .serializers import (
    GameSerializer,
    GameActionSerializer,
    PlayerStatRecordSerializer,
    RecordableStatSerializer,
    PlayerStatSerializer,
    GamePlayerSerializer,
    StartingLineupSerializer,
    SubstitutionSerializer,
    GameCurrentPlayersSerializer,
)
from sports_management.permissions import IsAdminOrCoachUser
from .services import (
    PlayerStatsSummaryService,
    RecordingService,
    TeamStatsSummaryService,
)
from django_filters.rest_framework import DjangoFilterBackend
from .filters import GameFilter


class PlayerStatViewSet(viewsets.ModelViewSet):
    queryset = PlayerStat.objects.select_related("player__team", "game", "stat_type")
    serializer_class = PlayerStatSerializer

    @action(detail=False, methods=["get"])
    def recordable_stats(self, request):
        game_id = request.query_params.get("game_id")
        if not game_id:
            return Response({"error": "game_id parameter required"}, status=400)

        try:
            game = Game.objects.get(pk=game_id)
            stats = SportStatType.objects.filter(
                sport=game.sport, composite_stats__isnull=True
            ).annotate(
                current_period=Value(game.current_period, output_field=IntegerField())
            )
            serializer = RecordableStatSerializer(stats, many=True)
            return Response(serializer.data)
        except Game.DoesNotExist:
            return Response({"error": "Game not found"}, status=404)

    @action(detail=False, methods=["post"])
    def record(self, request):
        serializer = PlayerStatRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = RecordingService(serializer.validated_data)
        service.validate()  # will raise a DRF ValidationError if not in progress
        stat = service.record()
        return Response(PlayerStatSerializer(stat).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def player_stats_summary(self, request):
        game_id = request.query_params.get("game_id")
        team = request.query_params.get("team")
        if not game_id:
            return Response({"error": "game_id parameter required"}, status=400)
        try:
            service = PlayerStatsSummaryService(game_id=game_id, team_filter=team)
        except Game.DoesNotExist:
            return Response({"error": "Game not found"}, status=404)
        data = service.get_summary()
        return Response(data)

    @action(detail=False, methods=["get"])
    def team_stats_summary(self, request):
        game_id = request.query_params.get("game_id")
        if not game_id:
            return Response({"error": "game_id parameter required"}, status=400)
        try:
            service = TeamStatsSummaryService(game_id=game_id)
        except Game.DoesNotExist:
            return Response({"error": "Game not found"}, status=404)
        data = service.get_summary()
        return Response(data)


class GameViewSet(viewsets.ModelViewSet):
    queryset = Game.objects.select_related(
        "sport", "home_team", "away_team"
    ).prefetch_related(
        "starting_lineup__player__user",
        "substitutions__substitute_in__user",
        "substitutions__substitute_out__user",
    )
    serializer_class = GameSerializer
    permission_classes = [IsAdminOrCoachUser]
    filter_backends = [DjangoFilterBackend]
    filterset_class = GameFilter

    def perform_create(self, serializer):
        serializer.save(creator=self.request.user)

    @action(detail=True, methods=["post"])
    def manage(self, request, pk=None):
        game = self.get_object()
        serializer = GameActionSerializer(data=request.data, context={"game": game})
        serializer.is_valid(raise_exception=True)

        action = serializer.validated_data["action"]
        if action == "start":
            game.start_game()
        elif action == "complete":
            game.complete_game()
        elif action == "next_period":
            game.next_period()

        return Response(GameSerializer(game).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def update_scores(self, request, pk=None):
        game = self.get_object()
        game.update_scores()
        return Response(GameSerializer(game).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def players(self, request, pk=None):
        game = self.get_object()
        players = (
            Player.objects.select_related("user", "team")
            .prefetch_related("position")
            .filter(team__in=[game.home_team, game.away_team])
            .distinct()
        )
        serializer = GamePlayerSerializer(
            players, many=True, context={"request": request, "game": game}
        )

        teams = {
            "home_team": [p for p in serializer.data if p["team_side"] == "home_team"],
            "away_team": [p for p in serializer.data if p["team_side"] == "away_team"],
        }

        return Response(teams)

    @action(detail=True, methods=["get"])
    def current_players(self, request, pk=None):
        game = self.get_object()
        serializer = GameCurrentPlayersSerializer(game, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["get", "post", "delete"])
    def starting_lineup(self, request, pk=None):
        """Manage starting lineup for the game"""
        game = self.get_object()

        if request.method == "GET":
            return self._get_starting_lineup(game)
        elif request.method == "POST":
            return self._update_starting_lineup(game, request.data)
        elif request.method == "DELETE":
            return self._delete_starting_lineup(game)

    def _get_starting_lineup(self, game):
        lineup = game.starting_lineup.select_related("player", "team")
        serializer = StartingLineupSerializer(lineup, many=True)

        # Split players into home/away teams
        home_players = []
        away_players = []

        for player_data in serializer.data:
            if player_data["team_side"] == "home":
                home_players.append(player_data)
            else:
                away_players.append(player_data)

        return Response(
            {"home_starting_lineup": home_players, "away_starting_lineup": away_players}
        )

    def _update_starting_lineup(self, game, data):
        """Handle lineup updates including empty submissions"""
        if game.status != Game.Status.SCHEDULED:
            return Response(
                {"error": "Lineups can only be set for scheduled games"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate request structure but allow empty arrays
        if not isinstance(data, dict) or "home_team" not in data or "away_team" not in data:
            return Response(
                {"error": "Payload must contain home_team and away_team arrays"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        home_data = data.get("home_team", [])
        away_data = data.get("away_team", [])

        # Validate team assignments (will skip if empty)
        try:
            if home_data:  # Only validate if data exists
                self._validate_team_players(game.home_team, home_data, "home_team", game.sport.max_players_on_field)
            if away_data:  # Only validate if data exists
                self._validate_team_players(game.away_team, away_data, "away_team", game.sport.max_players_on_field)
        except ValidationError as e:
            return Response({"error": e.detail}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # Clear existing lineup for teams that have data (empty array means clear)
            if "home_team" in data:  # Key exists (could be empty array)
                game.starting_lineup.filter(team=game.home_team).delete()
            if "away_team" in data:  # Key exists (could be empty array)
                game.starting_lineup.filter(team=game.away_team).delete()

            # Combine non-empty data for serializer
            combined_data = [p for p in home_data + away_data if p.get("player") is not None]
            
            if combined_data:
                serializer = StartingLineupSerializer(
                    data=combined_data,
                    many=True,
                    context={"game": game, "request": self.request},
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()

        # Return current state
        return Response({
            "home_team": StartingLineupSerializer(
                game.starting_lineup.filter(team=game.home_team),
                many=True
            ).data,
            "away_team": StartingLineupSerializer(
                game.starting_lineup.filter(team=game.away_team),
                many=True
            ).data,
            "lineup_status": game.get_lineup_status()
        }, status=status.HTTP_200_OK)
    
    def _validate_team_players(self, expected_team, players, team_side, max_players):
        """Validate players belong to team, and do not exceed max field players"""
        if not isinstance(players, list):
            raise ValidationError({team_side: "Must be an array of players"})

        # Skip validation if empty array
        if not players:
            return

        # Filter out any player entries that don't have a player ID
        player_user_ids = [p.get("player") for p in players if p.get("player")]

        if not player_user_ids:
            return  # No valid player IDs, allow submission

        # Validate count against max players allowed on field
        if len(player_user_ids) > max_players:
            raise ValidationError({
                team_side: f"You can only select up to {max_players} players for the starting lineup."
            })

        players_queryset = Player.objects.filter(user_id__in=player_user_ids)
        if players_queryset.count() != len(player_user_ids):
            raise ValidationError({team_side: "Invalid player IDs provided"})

        for player in players_queryset:
            if player.team != expected_team:
                raise ValidationError(
                    {team_side: f"Player {player.user.id} belongs to the wrong team"}
                )

    def _delete_starting_lineup(self, game):
        if game.status != Game.Status.SCHEDULED:
            return Response(
                {"error": "Can only clear lineup for scheduled games"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        count, _ = game.starting_lineup.all().delete()
        return Response({"deleted": count}, status=status.HTTP_204_NO_CONTENT)


class SubstitutionViewSet(viewsets.ModelViewSet):
    queryset = Substitution.objects.select_related(
        "game", "substitute_in", "substitute_out"
    )
    serializer_class = SubstitutionSerializer
    permission_classes = [IsAdminOrCoachUser]

    def get_queryset(self):
        game_id = self.request.query_params.get("game_id")
        if game_id:
            return self.queryset.filter(game_id=game_id)
        return self.queryset
    
    @action(detail=False, methods=["post"], url_path="bulk_create")
    def bulk_create(self, request):
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        self.perform_bulk_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def undo(self, request, pk=None):
        substitution = self.get_object()
        substitution.delete()
        return Response({"status": "Substitution undone"}, status=status.HTTP_200_OK)
