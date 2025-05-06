from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from rest_framework.exceptions import ValidationError
from django.db.models import Value, IntegerField
from rest_framework.pagination import PageNumberPagination
from .models import Game, PlayerStat, Substitution
from teams.models import Player
from sports.models import SportStatType, Sport
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
    TeamStatsComparisonService,
    BoxscoreService
)
from django_filters.rest_framework import DjangoFilterBackend
from .filters import GameFilter
from collections import defaultdict


# Custom pagination class specifically for games
class GamePagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


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
                sport=game.sport, is_record=True
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
    
    @action(detail=False, methods=["get"])
    def team_stats_comparison(self, request):
        game_id = request.query_params.get("game_id")
        if not game_id:
            return Response({"error": "game_id parameter required"}, status=400)
        try:
            service = TeamStatsComparisonService(game_id=game_id)
        except Game.DoesNotExist:
            return Response({"error": "Game not found"}, status=404)
        data = service.get_comparison()
        return Response(data)
    
    @action(detail=False, methods=["get"])
    def boxscore(self, request):
        game_id = request.query_params.get("game_id")
        if not game_id:
            return Response({"error": "game_id parameter required"}, status=400)
        try:
            service = BoxscoreService(game_id=game_id)
        except Game.DoesNotExist:
            return Response({"error": "Game not found"}, status=404)
        data = service.get_boxscore()
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
    pagination_class = GamePagination

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
        """Get the current starting lineup for a game"""
        return Response(
            {
                "home_team": StartingLineupSerializer(
                    game.starting_lineup.filter(team=game.home_team), many=True
                ).data,
                "away_team": StartingLineupSerializer(
                    game.starting_lineup.filter(team=game.away_team), many=True
                ).data,
                "lineup_status": game.get_lineup_status(),
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"])
    def game_flow(self, request, pk=None):
        game = self.get_object()

        if game.status != Game.Status.COMPLETED:
            return Response(
                {"error": "Game flow data is only available for completed games"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        stats = (
            PlayerStat.objects.filter(
                game=game, 
                stat_type__is_counter=True, 
                stat_type__point_value__gt=0
            )
            .select_related("player__user", "player__team", "stat_type")
            .order_by("timestamp")
        )

        scoring_type = "sets" if game.sport.scoring_type == Sport.SCORING_TYPES.SETS else "points"
        periods = []

        def format_period_label(period_num, sport):
            if scoring_type == "sets":
                return f"{ordinal(period_num)} Set"
            
            if sport.has_period:
                if sport.has_overtime and period_num > sport.max_period:
                    ot_num = period_num - sport.max_period
                    return "OT" if ot_num == 1 else f"{ot_num}OT"
                return f"{ordinal(period_num)}"
            return "Game"

        def ordinal(n):
            if 11 <= (n % 100) <= 13:
                suffix = 'th'
            else:
                suffix = ['th', 'st', 'nd', 'rd', 'th'][min(n % 10, 4)]
            return f"{n}{suffix}"

        # Get actual periods from stats
        stat_periods = sorted({stat.period for stat in stats})
        first_period = min(stat_periods) if stat_periods else 1
        last_period = max(stat_periods) if stat_periods else 1

        if scoring_type == "sets":
            sets = game.sets.all().order_by("period")
            for s in sets:
                periods.append({
                    "number": s.period,
                    "label": format_period_label(s.period, game.sport),
                    "home_score": s.home_team_score,
                    "away_score": s.away_team_score,
                    "winner": s.winner_id,
                    "completed": True,
                    "events_count": stats.filter(period=s.period).count(),
                })
            home_total = game.sets.filter(winner=game.home_team).count()
            away_total = game.sets.filter(winner=game.away_team).count()
        else:
            for period in range(1, game.current_period + 1):
                period_stats = stats.filter(period=period)
                home_score = sum(s.stat_type.point_value for s in period_stats 
                            if s.player.team_id == game.home_team_id)
                away_score = sum(s.stat_type.point_value for s in period_stats 
                            if s.player.team_id == game.away_team_id)
                
                periods.append({
                    "number": period,
                    "label": format_period_label(period, game.sport),
                    "home_score": home_score,
                    "away_score": away_score,
                    "winner": (
                        game.home_team_id if home_score > away_score
                        else game.away_team_id if away_score > home_score 
                        else None
                    ),
                    "completed": True,
                    "events_count": period_stats.count(),
                })
            home_total = game.home_team_score
            away_total = game.away_team_score

        # Track live score per event
        if scoring_type == "sets":
            events_by_period = defaultdict(list)
            
            # Add starting event for each period with correct label
            for period in periods:
                events_by_period[period["number"]].append({
                    "id": None,
                    "player": "",
                    "stat_name": "Start of Set",
                    "point_value": 0,
                    "team": "",
                    "team_side": "",
                    "period": period["number"],
                    "period_label": format_period_label(period["number"], game.sport),
                    "timestamp": game.started_at.isoformat() if game.started_at else "",
                    "current_score": {
                        "home": 0,
                        "away": 0
                    }
                })

            # Process actual events
            for stat in stats:
                team_side = "home" if stat.player.team_id == game.home_team_id else "away"
                period_events = events_by_period[stat.period]
                
                current_score = period_events[-1]["current_score"].copy()
                current_score[team_side] += stat.stat_type.point_value
                
                period_events.append({
                    "id": stat.id,
                    "player": stat.player.user.get_full_name(),
                    "stat_name": stat.stat_type.display_name,
                    "point_value": stat.stat_type.point_value,
                    "team": stat.player.team.abbreviation,
                    "team_side": team_side,
                    "period": stat.period,
                    "period_label": format_period_label(stat.period, game.sport),
                    "timestamp": stat.timestamp.isoformat(),
                    "current_score": current_score
                })

            # Add ending event for each period with correct label
            for period in periods:
                period_num = period["number"]
                
                events_by_period[period_num].append({
                    "id": None,
                    "player": "",
                    "stat_name": "End of Set",
                    "point_value": 0,
                    "team": "",
                    "team_side": "",
                    "period": period_num,
                    "period_label": format_period_label(period_num, game.sport),
                    "timestamp": game.ended_at.isoformat() if game.ended_at else "",
                    "current_score": {
                        "home": period["home_score"],
                        "away": period["away_score"]
                    }
                })

            events = dict(events_by_period)
        else:
            events = []
            
            # Add starting event with first period's label
            first_period_label = format_period_label(first_period, game.sport)
            events.append({
                "id": None,
                "player": "",
                "stat_name": "Start of Game",
                "point_value": 0,
                "team": "",
                "team_side": "",
                "period": first_period,
                "period_label": first_period_label,
                "timestamp": game.started_at.isoformat() if game.started_at else "",
                "current_score": {
                    "home": 0,
                    "away": 0
                }
            })

            # Process actual events
            current_score = {"home": 0, "away": 0}
            for stat in stats:
                team_side = "home" if stat.player.team_id == game.home_team_id else "away"
                current_score[team_side] += stat.stat_type.point_value
                
                events.append({
                    "id": stat.id,
                    "player": stat.player.user.get_full_name(),
                    "stat_name": stat.stat_type.display_name,
                    "point_value": stat.stat_type.point_value,
                    "team": stat.player.team.abbreviation,
                    "team_side": team_side,
                    "period": stat.period,
                    "period_label": format_period_label(stat.period, game.sport),
                    "timestamp": stat.timestamp.isoformat(),
                    "current_score": current_score.copy()
                })

            # Add ending event with last period's label
            last_period_label = format_period_label(last_period, game.sport)
            events.append({
                "id": None,
                "player": "",
                "stat_name": "End of Game",
                "point_value": 0,
                "team": "",
                "team_side": "",
                "period": last_period,
                "period_label": last_period_label,
                "timestamp": game.ended_at.isoformat() if game.ended_at else "",
                "current_score": {
                    "home": home_total,
                    "away": away_total
                }
            })  

        response_data = {
            "game": {
                "id": game.id,
                "name": f"{game.home_team.name} vs {game.away_team.name}",
                "status": game.status,
                "started_at": game.started_at.isoformat() if game.started_at else None,
                "ended_at": game.ended_at.isoformat() if game.ended_at else None,
                "duration": str(game.duration) if game.duration else None,
                "winner": game.winner.id if game.winner else None,
                "sport": {
                    "id": game.sport.id,
                    "name": game.sport.name,
                    "scoring_type": scoring_type,
                    "has_periods": game.sport.has_period,
                    "has_overtime": game.sport.has_overtime,
                    "max_period": game.sport.max_period
                },
                "teams": {
                    "home": {
                        "id": game.home_team.id,
                        "name": game.home_team.name,
                        "abbreviation": game.home_team.abbreviation,
                        "score": home_total,
                        "color": game.home_team.color or "#000000"
                    },
                    "away": {
                        "id": game.away_team.id,
                        "name": game.away_team.name,
                        "abbreviation": game.away_team.abbreviation,
                        "score": away_total,
                        "color": game.away_team.color or "#900029"
                    }
                }
            },
            "scoring": {
                "type": scoring_type,
                "periods": periods,
                "home_total": home_total,
                "away_total": away_total,
                "win_threshold": (
                    game.sport.win_threshold 
                    if scoring_type == "sets" 
                    else None
                )
            },
            "events": events
        }

        return Response(response_data)
    
    def _update_starting_lineup(self, game, data):
        """Handle lineup updates including empty submissions"""
        if game.status != Game.Status.SCHEDULED:
            return Response(
                {"error": "Lineups can only be set for scheduled games"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate request structure but allow empty arrays
        if (
            not isinstance(data, dict)
            or "home_team" not in data
            or "away_team" not in data
        ):
            return Response(
                {"error": "Payload must contain home_team and away_team arrays"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        home_data = data.get("home_team", [])
        away_data = data.get("away_team", [])

        # Validate team assignments (will skip if empty)
        try:
            if home_data:  # Only validate if data exists
                self._validate_team_players(
                    game.home_team,
                    home_data,
                    "home_team",
                    game.sport.max_players_on_field,
                )
            if away_data:  # Only validate if data exists
                self._validate_team_players(
                    game.away_team,
                    away_data,
                    "away_team",
                    game.sport.max_players_on_field,
                )
        except ValidationError as e:
            return Response({"error": e.detail}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # Clear existing lineup for teams that have data (empty array means clear)
            if "home_team" in data:  # Key exists (could be empty array)
                game.starting_lineup.filter(team=game.home_team).delete()
            if "away_team" in data:  # Key exists (could be empty array)
                game.starting_lineup.filter(team=game.away_team).delete()

            # Combine non-empty data for serializer
            combined_data = [
                p for p in home_data + away_data if p.get("player") is not None
            ]

            if combined_data:
                serializer = StartingLineupSerializer(
                    data=combined_data,
                    many=True,
                    context={"game": game, "request": self.request},
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()

        # Return current state
        return Response(
            {
                "home_team": StartingLineupSerializer(
                    game.starting_lineup.filter(team=game.home_team), many=True
                ).data,
                "away_team": StartingLineupSerializer(
                    game.starting_lineup.filter(team=game.away_team), many=True
                ).data,
                "lineup_status": game.get_lineup_status(),
            },
            status=status.HTTP_200_OK,
        )

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
            raise ValidationError(
                {
                    team_side: f"You can only select up to {max_players} players for the starting lineup."
                }
            )

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

    def perform_bulk_create(self, serializer):
        created = Substitution.objects.bulk_create(
            [Substitution(**item) for item in serializer.validated_data]
        )
        return Substitution.objects.filter(pk__in=[obj.pk for obj in created])

    @action(detail=False, methods=["post"], url_path="bulk_create")
    def bulk_create(self, request):
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        instances = self.perform_bulk_create(serializer)

        output_serializer = self.get_serializer(instances, many=True)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def undo(self, request, pk=None):
        substitution = self.get_object()
        substitution.delete()
        return Response({"status": "Substitution undone"}, status=status.HTTP_200_OK)
