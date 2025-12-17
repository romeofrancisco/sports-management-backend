from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction, models
from rest_framework.exceptions import ValidationError
from django.db.models import Value, IntegerField, Q
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404


def get_coach_teams(coach_profile):
    """Helper function to get teams where coach is either head coach or assistant coach"""
    from teams.models import Team

    return Team.objects.filter(
        Q(head_coach=coach_profile) | Q(assistant_coach=coach_profile)
    )


from .models import (
    Game,
    PlayerStat,
    Substitution,
    GameCoachPermission,
    GameSet,
    StartingLineup,
    ScoreUpdate,
)
from teams.models import Player
from sports.models import SportStatType, Sport
from users.models import User
from .serializers import (
    GameSerializer,
    GameDetailSerializer,
    GameActionSerializer,
    PlayerStatRecordSerializer,
    RecordableStatSerializer,
    PlayerStatSerializer,
    GamePlayerSerializer,
    StartingLineupSerializer,
    SubstitutionSerializer,
    GameCurrentPlayersSerializer,
    GameCoachPermissionSerializer,
    ScoreUpdateSerializer,
    GameScoreSerializer,
)
from rest_framework.permissions import IsAuthenticated
from sports_management.permissions import (
    IsAdminOrCoachUser,
    CanManageGamePermission,
    CanCreateGamePermission,
)
from rest_framework.exceptions import PermissionDenied
from .services import (
    PlayerStatsSummaryService,
    RecordingService,
    TeamStatsSummaryService,
    TeamStatsComparisonService,
    BoxscoreService,
    GameLeaderService,
    BulkRecordingService,
    FastStatRecordingService,
)
from .signals import send_score_update, send_game_status_update
from django_filters.rest_framework import DjangoFilterBackend
from .filters import GameFilter
from collections import defaultdict
import time
import logging
import traceback
from django.db import models


logger = logging.getLogger(__name__)


# Custom pagination class specifically for games
class GamePagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100


# Custom pagination for player stats
class PlayerStatPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class PlayerStatViewSet(viewsets.ModelViewSet):
    queryset = PlayerStat.objects.select_related("player__team", "game", "stat_type")
    serializer_class = PlayerStatSerializer
    pagination_class = PlayerStatPagination
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"])
    def recordable_stats(self, request):
        game_id = request.query_params.get("game_id")
        if not game_id:
            return Response({"error": "game_id parameter required"}, status=400)

        try:
            game = Game.objects.get(pk=game_id)
            stats = SportStatType.objects.filter(
                sport=game.sport, is_record=True, is_active=True
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

    @action(detail=False, methods=["post"])
    def bulk_record(self, request):
        """
        Record multiple stats in a single operation for improved performance.
        Expected data format:
        {
            "stats": [
                {
                    "game": game_id,
                    "player": player_id,
                    "stat_type": stat_type_id,
                    "period": period_number,
                    "value": stat_value
                },
                ...
            ]
        }
        """
        start_time = time.time()

        if not isinstance(request.data, dict) or "stats" not in request.data:
            return Response(
                {"error": "Invalid data format. Expected 'stats' array."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        stats_data = request.data.get("stats", [])

        if not stats_data:
            return Response(
                {"error": "No stats provided for recording."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(stats_data) > 100:
            return Response(
                {"error": "Cannot record more than 100 stats at once."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Extract game_id from the first stat to initialize the service
            game_id = stats_data[0].get("game")
            if not game_id:
                return Response(
                    {"error": "Game ID is required in stat data."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            service = BulkRecordingService(game_id)

            # Convert stats_data to the format expected by BulkRecordingService
            bulk_stats_data = []
            for stat_data in stats_data:
                bulk_stat = {
                    "player_id": stat_data.get("player"),
                    "stat_type_id": stat_data.get("stat_type"),
                }
                bulk_stats_data.append(bulk_stat)

            recorded_stats = service.bulk_record(bulk_stats_data)

            processing_time = time.time() - start_time
            logger.info(
                f"Bulk recorded {len(recorded_stats)} stats in {processing_time:.2f}s"
            )

            return Response(
                {
                    "message": f"Successfully recorded {len(recorded_stats)} stats",
                    "stats": [
                        PlayerStatSerializer(stat).data for stat in recorded_stats
                    ],
                    "processing_time": f"{processing_time:.2f}s",
                },
                status=status.HTTP_201_CREATED,
            )

        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error in bulk recording: {str(e)}")
            logger.error(traceback.format_exc())
            return Response(
                {"error": "An error occurred while recording stats"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"])
    def record_fast(self, request):
        """
        Record a single stat with optimized performance for faster recording.
        Uses the FastStatRecordingService for minimal database queries.
        """
        start_time = time.time()
        serializer = PlayerStatRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            service = FastStatRecordingService(serializer.validated_data)
            stat = service.record_fast()

            processing_time = time.time() - start_time
            logger.info(f"Fast recorded stat in {processing_time:.3f}s")

            return Response(
                {
                    "stat": PlayerStatSerializer(stat).data,
                    "processing_time": f"{processing_time:.3f}s",
                },
                status=status.HTTP_201_CREATED,
            )

        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error in fast recording: {str(e)}")
            logger.error(traceback.format_exc())
            return Response(
                {"error": "An error occurred while recording the stat"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"])
    def bulk_record_optimized(self, request):
        """
        Ultra-fast bulk recording using raw SQL for very large operations.
        Use this for recording more than 20 stats when maximum performance is needed.
        """
        start_time = time.time()

        if not isinstance(request.data, dict) or "stats" not in request.data:
            return Response(
                {"error": "Invalid data format. Expected 'stats' array."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        stats_data = request.data.get("stats", [])

        if not stats_data:
            return Response(
                {"error": "No stats provided for recording."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(stats_data) > 100:
            return Response(
                {"error": "Cannot record more than 100 stats at once."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(stats_data) < 20:
            return Response(
                {"error": "Use regular bulk_record for less than 20 stats."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            # Extract game_id from the first stat to initialize the service
            game_id = stats_data[0].get("game")
            if not game_id:
                return Response(
                    {"error": "Game ID is required in stat data."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            service = BulkRecordingService(game_id)

            # Convert stats_data to the format expected by BulkRecordingService
            bulk_stats_data = []
            for stat_data in stats_data:
                bulk_stat = {
                    "player_id": stat_data.get("player"),
                    "stat_type_id": stat_data.get("stat_type"),
                }
                bulk_stats_data.append(bulk_stat)

            result = service.bulk_record_optimized(bulk_stats_data)

            processing_time = time.time() - start_time
            logger.info(
                f"Optimized bulk recorded {result['count']} stats in {processing_time:.2f}s"
            )

            return Response(
                {
                    "message": f"Successfully recorded {result['count']} stats using optimized method",
                    "count": result["count"],
                    "processing_time": f"{processing_time:.2f}s",
                    "stats_ids": result.get("stats_ids", []),
                },
                status=status.HTTP_201_CREATED,
            )

        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error in optimized bulk recording: {str(e)}")
            logger.error(traceback.format_exc())
            return Response(
                {"error": "An error occurred while recording stats"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"])
    def player_stats_summary(self, request):
        game_id = request.query_params.get("game_id")
        team = request.query_params.get("team")
        if not game_id:
            return Response({"error": "game_id parameter required"}, status=400)

        # Add for_calculation flag to optimize query based on usage
        for_calculation = request.query_params.get("for_calculation") == "true"
        use_raw_sql = request.query_params.get("use_raw_sql") == "true"

        # Log the start time for performance monitoring
        start_time = time.time()

        try:
            # Pass additional flags for performance optimization
            service = PlayerStatsSummaryService(game_id=game_id, team_filter=team)
            data = service.get_summary(
                for_calculation=for_calculation, use_raw_sql=use_raw_sql
            )

            # Log the time taken to process the request
            processing_time = time.time() - start_time
            logger.info(
                f"Stats summary processed in {processing_time:.2f}s for game {game_id}"
            )

            return Response(data)
        except Game.DoesNotExist:
            return Response({"error": "Game not found"}, status=404)
        except Exception as e:
            logger.error(f"Error processing player stats: {str(e)}")
            return Response({"error": str(e)}, status=500)

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

    @action(detail=False, methods=["delete"])
    def undo_last_stat(self, request):
        """
        Undo the last recorded stat for a specific game.
        Deletes the most recent PlayerStat record based on timestamp.
        """
        game_id = request.query_params.get("game_id")

        if not game_id:
            return Response({"error": "game_id parameter required"}, status=400)

        try:
            game = Game.objects.get(pk=game_id)

            # Get the most recent PlayerStat for this game
            last_stat = (
                PlayerStat.objects.filter(game=game).order_by("-timestamp").first()
            )

            if not last_stat:
                return Response(
                    {"error": "No stats found for this game to undo"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            # Store stat info for response before deletion
            stat_info = {
                "id": last_stat.id,
                "player_name": f"{last_stat.player.user.first_name} {last_stat.player.user.last_name}",
                "stat_type": last_stat.stat_type.name,
                "period": last_stat.period,
                "timestamp": last_stat.timestamp,
            }

            # Delete the stat using transaction to ensure consistency
            with transaction.atomic():
                last_stat.delete()
                # Game scores will be updated automatically via signals

            return Response(
                {
                    "message": "Last stat record successfully undone",
                    "undone_stat": stat_info,
                },
                status=status.HTTP_200_OK,
            )

        except Game.DoesNotExist:
            return Response(
                {"error": "Game not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            print(f"Exception occurred: {str(e)}")
            import traceback

            traceback.print_exc()
            return Response(
                {"error": "An error occurred while undoing the last stat"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class GameViewSet(viewsets.ModelViewSet):
    queryset = Game.objects.select_related(
        "sport", "home_team", "away_team"
    ).prefetch_related(
        "starting_lineup__player__user",
        "substitutions__substitute_in__user",
        "substitutions__substitute_out__user",
        "coach_permissions__coach",
    )
    serializer_class = GameSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_class = GameFilter
    pagination_class = GamePagination

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return GameDetailSerializer
        elif self.action in ['update_score', 'set_score']:
            return GameScoreSerializer
        return GameSerializer

    def get_permissions(self):
        """
        Instantiate and return the list of permissions that this view requires.
        """
        if self.action == "create":
            permission_classes = [CanCreateGamePermission]
        elif self.action in [
            "manage",
            "update_scores",
            "partial_update",
            "update",
            "destroy",
        ]:
            permission_classes = [CanManageGamePermission]
        else:
            permission_classes = [IsAuthenticated]

        return [permission() for permission in permission_classes]

    def get_queryset(self):
        """
        Filter games based on game type and user role:
        - League, tournament, and practice games are filtered by team ownership for coaches/players
        - Admin users can see all games
        """
        queryset = super().get_queryset()
        user = self.request.user

        # If admin, return all games
        if user.is_admin:
            return queryset

        # Filter games based on user role - only show games for their teams
        if hasattr(user, "coach_profile"):
            # For coaches: show games for teams they coach AND games they have explicit permission to manage
            from django.db.models import Q
            from teams.models import Team

            coach_teams = Team.objects.filter(
                Q(head_coach=user.coach_profile) | Q(assistant_coach=user.coach_profile)
            )
            
            # Include games for teams they coach
            team_games_filter = models.Q(home_team__in=coach_teams) | models.Q(away_team__in=coach_teams)
            
            # Also include games they have explicit permission to manage (typically league games)
            assigned_games_filter = models.Q(coach_permissions__coach=user)
            
            return queryset.filter(team_games_filter | assigned_games_filter).distinct()
        

        elif hasattr(user, "player_profile"):
            # For players: all game types but only for their team
            player_team = user.player_profile.team
            if player_team:
                return queryset.filter(
                    models.Q(home_team=player_team) | models.Q(away_team=player_team)
                )
            else:
                # Player has no team, only show league/tournament games
                return queryset.filter(
                    type__in=[Game.Type.LEAGUE, Game.Type.TOURNAMENT]
                )

        # Default: only show league and tournament games for other users
        return queryset.filter(type__in=[Game.Type.LEAGUE, Game.Type.TOURNAMENT])

    def perform_create(self, serializer):
        user = self.request.user
        game_type = serializer.validated_data.get("type", Game.Type.PRACTICE)

        # Admins can create any type of game
        if user.is_admin:
            game = serializer.save(creator=user)
            # Send notification for all games created by admin
            self._send_game_notification(game, user)
            return

        # Coaches can only create practice games for their teams
        if user.is_coach and hasattr(user, "coach_profile"):
            # Restrict to practice games only
            if game_type != Game.Type.PRACTICE:  # PRACTICE maps to practice games
                raise PermissionDenied("Coaches can only create practice games")

            # Check if coach owns either team in the game
            home_team = serializer.validated_data.get("home_team")
            away_team = serializer.validated_data.get("away_team")
            coach_teams = get_coach_teams(user.coach_profile)

            if home_team not in coach_teams and away_team not in coach_teams:
                raise PermissionDenied("You can only create games for teams you coach")

            game = serializer.save(creator=user)
            # Send notification for practice games too
            self._send_game_notification(game, user)
            return

        # Deny access for other users
        raise PermissionDenied("You don't have permission to create games")

    def perform_update(self, serializer):
        """Update game and send notification"""
        user = self.request.user
        game = serializer.save()
        # Send update notification
        self._send_game_notification(game, creator=user, is_update=True)

    def _send_game_notification(self, game, creator=None, is_update=False):
        """Send notification for a newly created or updated game"""
        try:
            from notifications.utils import send_game_notification
            send_game_notification(game, creator=creator, is_update=is_update)
        except Exception as e:
            logger.error(f"Failed to send game notification for game {game.id}: {e}")

    def perform_destroy(self, instance):
        """
        Custom destroy method to handle set-based games properly
        and ensure all related objects are deleted in correct order
        """
        from django.db import transaction

        # Store the game ID before any deletion attempts
        game_id = instance.id

        try:
            with transaction.atomic():
                # For set-based games, explicitly delete GameSet records first
                if (
                    hasattr(instance.sport, "scoring_type")
                    and instance.sport.scoring_type == Sport.SCORING_TYPES.SETS
                ):
                    # Delete all related GameSet records using the stored game_id
                    GameSet.objects.filter(game_id=game_id).delete()

                # Delete other related objects that might not cascade properly
                # Use direct queries with game_id to avoid issues with the instance
                PlayerStat.objects.filter(game_id=game_id).delete()
                Substitution.objects.filter(game_id=game_id).delete()
                GameCoachPermission.objects.filter(game_id=game_id).delete()

                # Use the StartingLineup model's related name
                StartingLineup.objects.filter(game_id=game_id).delete()

                # Finally delete the game instance
                instance.delete()

        except Exception as e:
            logger.error(f"Error deleting game {game_id}: {str(e)}")
            # For database consistency issues, try to clean up orphaned records
            try:
                # Clean up any orphaned records using the stored game_id
                GameSet.objects.filter(game_id=game_id).delete()
                PlayerStat.objects.filter(game_id=game_id).delete()
                Substitution.objects.filter(game_id=game_id).delete()
                GameCoachPermission.objects.filter(game_id=game_id).delete()

                StartingLineup.objects.filter(game_id=game_id).delete()

                # Try to get a fresh instance and delete it
                try:
                    fresh_instance = Game.objects.get(id=game_id)
                    fresh_instance.delete()
                except Game.DoesNotExist:
                    # Game is already deleted, which is what we wanted
                    logger.info(f"Game {game_id} was already deleted during cleanup")

            except Exception as cleanup_error:
                logger.error(
                    f"Error during cleanup for game {game_id}: {str(cleanup_error)}"
                )
                # As a last resort, try to force delete using raw SQL
                try:
                    from django.db import connection

                    with connection.cursor() as cursor:
                        # Delete in correct order to avoid foreign key violations
                        cursor.execute(
                            "DELETE FROM games_gameset WHERE game_id = %s", [game_id]
                        )
                        cursor.execute(
                            "DELETE FROM games_playerstat WHERE game_id = %s", [game_id]
                        )
                        cursor.execute(
                            "DELETE FROM games_substitution WHERE game_id = %s",
                            [game_id],
                        )
                        cursor.execute(
                            "DELETE FROM games_gamecoachpermission WHERE game_id = %s",
                            [game_id],
                        )
                        cursor.execute(
                            "DELETE FROM games_startinglineup WHERE game_id = %s",
                            [game_id],
                        )
                        cursor.execute(
                            "DELETE FROM games_game WHERE id = %s", [game_id]
                        )
                    logger.info(f"Force deleted game {game_id} using raw SQL")
                except Exception as sql_error:
                    logger.error(
                        f"Failed to force delete game {game_id}: {str(sql_error)}"
                    )
                    raise

    @action(detail=True, methods=["get"])
    def game_leaders(self, request, pk=None):
        """Get the top players from each team for each leader category"""
        game = self.get_object()
        try:
            service = GameLeaderService(game_id=game.id, request=request)
            data = service.get_game_leaders()
            return Response(data)
        except Exception as e:
            logger.error(f"Error getting game leaders: {str(e)}")
            return Response(
                {"error": f"Failed to get game leaders: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["post"])
    def manage(self, request, pk=None):
        game = self.get_object()
        serializer = GameActionSerializer(data=request.data, context={"game": game})
        serializer.is_valid(raise_exception=True)

        action = serializer.validated_data["action"]
        old_status = game.status
        old_period = game.current_period

        if action == "start":
            game.start_game()
        elif action == "complete":
            game.complete_game()
        elif action == "next_period":
            game.next_period()

        # Send WebSocket update if status or period changed
        if game.status != old_status or game.current_period != old_period:
            send_game_status_update(game)

        return Response(GameSerializer(game).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def update_scores(self, request, pk=None):
        game = self.get_object()

        # Store old scores for comparison
        old_home_score = game.home_team_score
        old_away_score = game.away_team_score

        # Update scores
        game.update_scores()

        # Send WebSocket update if scores changed
        if (
            game.home_team_score != old_home_score
            or game.away_team_score != old_away_score
        ):
            send_score_update(game)

        return Response(GameSerializer(game).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def add_score(self, request, pk=None):
        """Add points to a team's score (for scoreboard-only sports)"""
        game = self.get_object()
        
        if game.sport.requires_stats:
            return Response(
                {'error': 'Use player stats for stat-tracking sports'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        team_id = request.data.get('team_id')
        points = request.data.get('points')

        if not team_id or points is None:
            return Response(
                {'error': 'team_id and points are required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate team
        if team_id == game.home_team.id:
            team = game.home_team
        elif team_id == game.away_team.id:
            team = game.away_team
        else:
            return Response(
                {'error': 'Invalid team_id'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Store old scores for WebSocket comparison
            old_home_score = game.home_team_score
            old_away_score = game.away_team_score

            with transaction.atomic():
                game.add_score(
                    team=team, 
                    points=int(points), 
                    updated_by=request.user,
                )

            # Send WebSocket update if scores changed
            if (
                game.home_team_score != old_home_score
                or game.away_team_score != old_away_score
            ):
                send_score_update(game)
                
            return Response({
                'message': f'Added {points} points to {team.name}',
                'game': GameSerializer(game).data
            })
        except ValidationError as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=["post"])
    def set_score(self, request, pk=None):
        """Set exact scores for both teams (for scoreboard-only sports)"""
        game = self.get_object()
        
        if game.sport.requires_stats:
            return Response(
                {'error': 'Use player stats for stat-tracking sports'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        home_score = request.data.get('home_score')
        away_score = request.data.get('away_score')

        if home_score is None or away_score is None:
            return Response(
                {'error': 'home_score and away_score are required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Store old scores for WebSocket comparison
            old_home_score = game.home_team_score
            old_away_score = game.away_team_score

            with transaction.atomic():
                game.set_score(
                    home_score=int(home_score), 
                    away_score=int(away_score),
                    updated_by=request.user
                )

            # Send WebSocket update if scores changed
            if (
                game.home_team_score != old_home_score
                or game.away_team_score != old_away_score
            ):
                send_score_update(game)
                
            return Response({
                'message': f'Set scores: {game.home_team.name} {home_score} - {game.away_team.name} {away_score}',
                'game': GameSerializer(game).data
            })
        except ValidationError as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['get'])
    def score_updates(self, request, pk=None):
        """Get score update history for a game"""
        game = self.get_object()
        
        if game.sport.requires_stats:
            return Response(
                {'error': 'Score updates not available for stat-tracking sports'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        updates = game.score_updates.select_related('team', 'updated_by').all()
        
        from .serializers import ScoreUpdateSerializer
        serializer = ScoreUpdateSerializer(updates, many=True)
        
        return Response({
            'score_updates': serializer.data,
            'total_count': updates.count()
        })

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
                game=game, stat_type__is_points=True, stat_type__point_value__gt=0
            )
            .select_related("player__user", "player__team", "stat_type")
            .order_by("timestamp")
        )

        scoring_type = (
            "sets" if game.sport.scoring_type == Sport.SCORING_TYPES.SETS else "points"
        )
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
                suffix = "th"
            else:
                suffix = ["th", "st", "nd", "rd", "th"][min(n % 10, 4)]
            return f"{n}{suffix}"

        # Get actual periods from stats        # Get all stats to determine periods, not just the scoring ones
        all_stats = (
            PlayerStat.objects.filter(game=game)
            .values_list("period", flat=True)
            .distinct()
        )
        stat_periods = sorted(all_stats) if all_stats else [1]
        first_period = min(stat_periods) if stat_periods else 1
        last_period = max(stat_periods) if stat_periods else 1

        if scoring_type == "sets":
            sets = game.sets.all().order_by("period")
            for s in sets:
                periods.append(
                    {
                        "number": s.period,
                        "label": format_period_label(s.period, game.sport),
                        "home_score": s.home_team_score,
                        "away_score": s.away_team_score,
                        "winner": s.winner_id,
                        "completed": True,
                        "events_count": PlayerStat.objects.filter(
                            game=game, period=s.period
                        ).count(),
                    }
                )
            home_total = game.sets.filter(winner=game.home_team).count()
            away_total = game.sets.filter(winner=game.away_team).count()
        else:
            for period in range(1, game.current_period + 1):
                period_stats = stats.filter(period=period)
                home_score = sum(
                    s.stat_type.point_value
                    for s in period_stats
                    if s.player.team_id == game.home_team_id
                )
                away_score = sum(
                    s.stat_type.point_value
                    for s in period_stats
                    if s.player.team_id == game.away_team_id
                )

                periods.append(
                    {
                        "number": period,
                        "label": format_period_label(period, game.sport),
                        "home_score": home_score,
                        "away_score": away_score,
                        "winner": (
                            game.home_team_id
                            if home_score > away_score
                            else game.away_team_id if away_score > home_score else None
                        ),
                        "completed": True,
                        "events_count": period_stats.count(),
                    }
                )
            home_total = game.home_team_score
            away_total = game.away_team_score

        # Track live score per event
        if scoring_type == "sets":
            events_by_period = defaultdict(list)

            # Create a tracking dictionary for scores by period
            period_scores = {
                period["number"]: {"home": 0, "away": 0} for period in periods
            }

            # Add starting event for each period with correct label
            for period in periods:
                events_by_period[period["number"]].append(
                    {
                        "id": None,
                        "player": "",
                        "stat_name": "Start of Set",
                        "point_value": 0,
                        "team": "",
                        "team_side": "",
                        "period": period["number"],
                        "period_label": format_period_label(
                            period["number"], game.sport
                        ),
                        "timestamp": (
                            game.started_at.isoformat() if game.started_at else ""
                        ),
                        "current_score": {"home": 0, "away": 0},
                    }
                )

            # Get ALL stats for the game, not just scoring stats
            set_stats = (
                PlayerStat.objects.filter(game=game)
                .select_related("player__user", "player__team", "stat_type")
                .order_by("timestamp")
            )

            # Process actual events for each set
            for stat in set_stats:
                team_side = (
                    "home" if stat.player.team_id == game.home_team_id else "away"
                )

                # Skip if this period doesn't exist in periods (safety check)
                if stat.period not in period_scores:
                    continue  # For volleyball/sets scoring, we need special logic to determine which team gets the point
                # In volleyball, one team always gets a point after each rally

                # Get stat name and type info for determining point allocation
                stat_name = stat.stat_type.name.upper() if stat.stat_type.name else ""
                stat_display_name = (
                    stat.stat_type.display_name.upper()
                    if stat.stat_type.display_name
                    else ""
                )
                is_point_stat = stat.stat_type.is_points
                point_value = stat.stat_type.point_value
                is_error = "ERROR" in stat_name or "ERROR" in stat_display_name

                # Determine which team gets the point in volleyball
                # Rule 1: If it's an error, the OTHER team gets the point
                # Rule 2: Otherwise, the team that made the play gets the point
                if team_side == "home":
                    if is_error:
                        # Home team made an error, away team gets the point
                        period_scores[stat.period]["away"] += 1
                    else:
                        # Home team made a positive play, they get the point
                        period_scores[stat.period]["home"] += 1
                else:  # away team
                    if is_error:
                        # Away team made an error, home team gets the point
                        period_scores[stat.period]["home"] += 1
                    else:
                        # Away team made a positive play, they get the point
                        period_scores[stat.period]["away"] += 1

                # Add the event with the current cumulative score for this period
                events_by_period[stat.period].append(
                    {
                        "id": stat.id,
                        "player": stat.player.user.get_full_name(),
                        "stat_name": stat.stat_type.display_name,
                        "point_value": point_value,
                        "team": stat.player.team.abbreviation,
                        "team_side": team_side,
                        "period": stat.period,
                        "period_label": format_period_label(stat.period, game.sport),
                        "timestamp": stat.timestamp.isoformat(),
                        "current_score": {
                            "home": period_scores[stat.period]["home"],
                            "away": period_scores[stat.period]["away"],
                        },
                    }
                )

            # Add ending event for each period with correct label
            for period in periods:
                period_num = period["number"]

                # Ensure the final score matches what's in the period data
                # This handles cases where the DB might have a different final score than our calculated one
                events_by_period[period_num].append(
                    {
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
                            "away": period["away_score"],
                        },
                    }
                )

            events = dict(events_by_period)
        else:
            events = []

            # Add starting event with first period's label
            first_period_label = format_period_label(first_period, game.sport)
            events.append(
                {
                    "id": None,
                    "player": "",
                    "stat_name": "Start of Game",
                    "point_value": 0,
                    "team": "",
                    "team_side": "",
                    "period": first_period,
                    "period_label": first_period_label,
                    "timestamp": game.started_at.isoformat() if game.started_at else "",
                    "current_score": {"home": 0, "away": 0},
                }
            )

            # Process actual events
            current_score = {"home": 0, "away": 0}
            for stat in stats:
                team_side = (
                    "home" if stat.player.team_id == game.home_team_id else "away"
                )
                current_score[team_side] += stat.stat_type.point_value

                events.append(
                    {
                        "id": stat.id,
                        "player": stat.player.user.get_full_name(),
                        "stat_name": stat.stat_type.display_name,
                        "point_value": stat.stat_type.point_value,
                        "team": stat.player.team.abbreviation,
                        "team_side": team_side,
                        "period": stat.period,
                        "period_label": format_period_label(stat.period, game.sport),
                        "timestamp": stat.timestamp.isoformat(),
                        "current_score": current_score.copy(),
                    }
                )

            # Add ending event with last period's label
            last_period_label = format_period_label(last_period, game.sport)
            events.append(
                {
                    "id": None,
                    "player": "",
                    "stat_name": "End of Game",
                    "point_value": 0,
                    "team": "",
                    "team_side": "",
                    "period": last_period,
                    "period_label": last_period_label,
                    "timestamp": game.ended_at.isoformat() if game.ended_at else "",
                    "current_score": {"home": home_total, "away": away_total},
                }
            )

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
                    "max_period": game.sport.max_period,
                },
                "teams": {
                    "home": {
                        "id": game.home_team.id,
                        "name": game.home_team.name,
                        "abbreviation": game.home_team.abbreviation,
                        "score": home_total,
                        "color": game.home_team.color or "#000000",
                    },
                    "away": {
                        "id": game.away_team.id,
                        "name": game.away_team.name,
                        "abbreviation": game.away_team.abbreviation,
                        "score": away_total,
                        "color": game.away_team.color or "#900029",
                    },
                },
            },
            "scoring": {
                "type": scoring_type,
                "periods": periods,
                "home_total": home_total,
                "away_total": away_total,
                "win_threshold": (
                    game.sport.win_threshold if scoring_type == "sets" else None
                ),
                "win_points_threshold": (
                    game.sport.win_points_threshold if scoring_type == "sets" else None
                ),
                "deciding_set_points_threshold": (
                    game.sport.deciding_set_points_threshold if scoring_type == "sets" else None
                ),
                "win_margin": (
                    game.sport.win_margin if scoring_type == "sets" else None
                ),
            },
            "events": events,
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

    @action(detail=True, methods=["get", "post", "delete"])
    def coach_assignments(self, request, pk=None):
        """
        Manage coach assignments for league and tournament games
        GET: List assigned coaches
        POST: Assign a coach to the game
        DELETE: Remove coach assignment
        """
        game = self.get_object()

        # Only allow coach assignments for league and tournament games
        if game.type == Game.Type.PRACTICE:
            return Response(
                {"error": "Coach assignments are only allowed for league and tournament games"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Only admins can manage coach assignments
        if not request.user.is_admin:
            return Response(
                {"error": "Only administrators can manage coach assignments"},
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.method == "GET":
            return self._get_coach_assignments(game)
        elif request.method == "POST":
            return self._assign_coach(game, request)
        elif request.method == "DELETE":
            return self._remove_coach_assignment(game, request)

    def _get_coach_assignments(self, game):
        """Get all coaches assigned to a game"""
        serializer = GameCoachPermissionSerializer(
            game.coach_permissions.all(), many=True, context={"request": self.request}
        )
        return Response(serializer.data)

    def _assign_coach(self, game, request):
        """Assign a coach to manage a game"""
        coach_id = request.data.get("coach_id")
        if not coach_id:
            return Response(
                {"error": "coach_id is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            coach = User.objects.get(id=coach_id, role=User.Role.COACH)
        except User.DoesNotExist:
            return Response(
                {"error": "Coach not found"}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            permission, created = game.assign_coach(coach, request.user)
            serializer = GameCoachPermissionSerializer(
                permission, context={"request": self.request}
            )

            response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            message = (
                "Coach assigned successfully" if created else "Coach already assigned"
            )

            return Response(
                {"message": message, "assignment": serializer.data},
                status=response_status,
            )
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def _remove_coach_assignment(self, game, request):
        """Remove a coach assignment from a game"""
        coach_id = request.data.get("coach_id")
        if not coach_id:
            return Response(
                {"error": "coach_id is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            coach = User.objects.get(id=coach_id, role=User.Role.COACH)
        except User.DoesNotExist:
            return Response(
                {"error": "Coach not found"}, status=status.HTTP_404_NOT_FOUND
            )

        deleted_count, _ = game.remove_coach(coach)

        if deleted_count > 0:
            return Response(
                {"message": "Coach assignment removed successfully"},
                status=status.HTTP_200_OK,
            )
        else:
            return Response(
                {"error": "Coach assignment not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=False, methods=["get"])
    def available_coaches(self, request):
        from rest_framework.reverse import reverse

        """Get list of all coaches available for assignment"""
        if not request.user.is_admin:
            return Response(
                {"error": "Only administrators can view available coaches"},
                status=status.HTTP_403_FORBIDDEN,
            )

        coaches = User.objects.filter(role=User.Role.COACH).select_related(
            "coach_profile"
        )
        coach_data = [
            {
                "id": coach.id,
                "name": coach.get_full_name(),
                "email": coach.email,
                "teams": (
                    [
                        {
                            "name": team.name,
                            "abbreviation": team.abbreviation,
                            "logo": (
                                request.build_absolute_uri(team.logo.url)
                                if hasattr(team, "logo") and team.logo
                                else None
                            ),
                        }
                        for team in get_coach_teams(coach.coach_profile)
                    ]
                    if hasattr(coach, "coach_profile")
                    else []
                ),
                "profile": (
                    request.build_absolute_uri(coach.profile.url)
                    if hasattr(coach, "profile") and coach.profile
                    else None
                ),
            }
            for coach in coaches
        ]

        return Response(coach_data)


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


class ScoreUpdateViewSet(viewsets.ModelViewSet):
    """ViewSet for managing score updates (for scoreboard-only sports)"""
    queryset = ScoreUpdate.objects.all()
    serializer_class = ScoreUpdateSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        game_id = self.request.query_params.get('game_id')
        if game_id:
            queryset = queryset.filter(game_id=game_id)
        return queryset.select_related('game', 'team', 'updated_by')

    def perform_create(self, serializer):
        game_id = self.request.query_params.get('game_id')
        if game_id:
            try:
                game = Game.objects.get(id=game_id)
                serializer.save(
                    updated_by=self.request.user, 
                    game=game,
                )
            except Game.DoesNotExist:
                raise ValidationError("Game not found")
        else:
            serializer.save(updated_by=self.request.user)

    def perform_update(self, serializer):
        # Prevent updates to score updates for audit trail
        return Response(
            {'error': 'Score updates cannot be modified'}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    def perform_destroy(self, instance):
        # Allow deletion but update game scores afterward
        game = instance.game
        super().perform_destroy(instance)
        if not game.sport.requires_stats:
            game.update_scores_manual()


class ScoreUpdateCreateView(generics.CreateAPIView):
    """Create view for score updates with game ID in URL path"""
    serializer_class = ScoreUpdateSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        game_id = self.kwargs['game_id']
        game = get_object_or_404(Game, id=game_id)
        
        # Validate that the game allows manual score updates
        if game.sport.requires_stats:
            raise ValidationError("Manual score updates not allowed for stat-tracking sports")
        
        serializer.save(
            updated_by=self.request.user, 
            game=game,
        )
