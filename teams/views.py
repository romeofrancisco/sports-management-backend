from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework.decorators import action
from .serializers import (
    PlayerInfoSerializer,
    CoachInfoSerializer,
    TeamSerializer,
    GameSummarySerializer,
    AcademicInfoSerializer,
)
from .models import Player, Coach, Team, AcademicInfo
from sports.models import Sport
from rest_framework.permissions import IsAuthenticated
from sports_management.permissions import IsAdminUser, IsCoachUser, IsAdminOrCoachUser
from rest_framework.response import Response
from rest_framework import status
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import F, Count, Q, Avg, Sum, Max, Min
from django.db import models
from .filters import CoachFilter, PlayerFilter
from rest_framework.pagination import PageNumberPagination
from django.core.exceptions import PermissionDenied
from datetime import datetime, timedelta
from django.utils import timezone

# Import models and serializers for analytics
from games.models import Game
from games.serializers import GameSerializer
from trainings.models import TrainingSession
from trainings.serializers import TrainingSessionListSerializer


class Pagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 50


class AcademicInfoViewSet(ModelViewSet):
    """
    ViewSet for managing AcademicInfo records.
    - List/Retrieve: All authenticated users can view
    - Create/Update/Delete: Only admins can modify
    """
    queryset = AcademicInfo.objects.all()
    serializer_class = AcademicInfoSerializer
    pagination_class = None  # Return all academic info without pagination
    filter_backends = [SearchFilter]
    filterset_fields = ["year_level", "course", "section"]
    search_fields = ["year_level", "course", "section"]
    
    def get_permissions(self):
        """
        Allow read operations for authenticated users,
        but restrict write operations to admins only
        """
        if self.action in ['list', 'retrieve']:
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsAdminUser]
        return [permission() for permission in permission_classes]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        request = self.request

        year_level = request.query_params.get("year_level")
        course = request.query_params.get("course")
        section = request.query_params.get("section")

        # Partial match for year_level
        if year_level:
            queryset = queryset.filter(year_level__icontains=year_level)

        # Optional: also make course & section partial-match
        if course:
            queryset = queryset.filter(course__icontains=course)

        if section:
            queryset = queryset.filter(section__icontains=section)

        return queryset

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated], url_path="paginated")
    def paginated(self, request):
        """Return paginated AcademicInfo results with optional column exclusion.

        Use this endpoint when the client prefers page-by-page fetching (for large
        datasets or when driving a Select component with server-side paging).
        
        Parameters:
        - page, page_size: Standard pagination parameters
        - year_level, course, section: Filter specific values
        - exclude: Column-based exclusion (comma-separated: 'course', 'section')
          - exclude=course: Groups by year_level only, excludes course and section columns
          - exclude=section: Groups by year_level and course, excludes section column
          - If both excluded, only year_level grouping is returned
        
        Examples:
        - GET /api/academic-info/paginated/?page=1&page_size=20
        - GET /api/academic-info/paginated/?exclude=course (year-level aggregation)
        - GET /api/academic-info/paginated/?exclude=section (year+course aggregation)
        - GET /api/academic-info/paginated/?exclude=course,section (same as exclude=course)
        """
        # Parse exclude parameter
        exclude_param = request.query_params.get("exclude", "").lower()
        excluded_columns = set(col.strip() for col in exclude_param.split(",") if col.strip())
        exclude_course = "course" in excluded_columns
        exclude_section = "section" in excluded_columns

        # Base queryset filtered by search params
        base_qs = self.filter_queryset(self.get_queryset())

        # Determine aggregation based on exclusions
        if exclude_course:
            # Group by year_level only
            qs = (
                base_qs.values("year_level")
                .annotate(player_count=Count("players", filter=Q(players__user__is_active=True)))
                .order_by("year_level")
            )
        elif exclude_section:
            # Group by year_level + course
            qs = (
                base_qs.values("year_level", "course")
                .annotate(player_count=Count("players", filter=Q(players__user__is_active=True)))
                .order_by("year_level", "course")
            )
        else:
            # Full queryset with player counts
            qs = base_qs.annotate(player_count=Count("players", filter=Q(players__user__is_active=True))).order_by("year_level", "course", "section")

        # Paginate
        paginator = Pagination()
        page = paginator.paginate_queryset(list(qs), request, view=self)
        if page is not None:
            if not page:  # Empty page
                return paginator.get_paginated_response([])

            # If using dict-style values() aggregation, return as-is
            if isinstance(page[0], dict):
                return paginator.get_paginated_response(list(page))

            # Otherwise, serialize model instances
            serializer = self.get_serializer(page, many=True)
            # Attach player_count if missing
            for idx, obj in enumerate(page):
                try:
                    serializer.data[idx]["player_count"] = getattr(obj, "player_count", 0)
                except Exception:
                    continue
            return paginator.get_paginated_response(serializer.data)

        # Fallback: return all if no pagination applied
        if qs:
            first_item = qs[0]
            if isinstance(first_item, dict):
                return Response(list(qs))
            serializer = self.get_serializer(qs, many=True)
            for idx, obj in enumerate(qs):
                try:
                    serializer.data[idx]["player_count"] = getattr(obj, "player_count", 0)
                except Exception:
                    continue
            return Response(serializer.data)

        # Completely empty queryset
        return Response([])


class TeamViewSet(ModelViewSet):
    queryset = Team.objects.all()
    lookup_field = "slug"
    serializer_class = TeamSerializer
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ["name"]
    filterset_fields = ["sport", "division"]
    pagination_class = Pagination

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def get_queryset(self):
        """
        Return teams based on user role:
        - Admin: All teams (active and inactive)
        - Coach: Only their own active teams
        - Player: Only their team if active
        - Others: Permission denied for all actions including list"""
        user = self.request.user
        # For admins, show all teams (active and inactive) with optimized queries
        if user.is_authenticated and hasattr(user, "is_admin") and user.is_admin:
            return Team.objects.select_related(
                "sport", "head_coach__user", "assistant_coach__user"
            ).prefetch_related(
                "players", "head_coach__sports", "assistant_coach__sports"
            )
            # For coaches, show only their active teams with optimized queries
        if hasattr(user, "coach_profile"):
            # Get teams where this coach is either head coach or assistant coach
            from django.db.models import Q

            return (
                Team.objects.filter(
                    Q(head_coach=user.coach_profile)
                    | Q(assistant_coach=user.coach_profile),
                    is_active=True  # Only active teams for coaches
                )
                .select_related("sport", "head_coach__user", "assistant_coach__user")
                .prefetch_related(
                    "players", "head_coach__sports", "assistant_coach__sports"
                )
            )
            # For players, show only their team if active with optimized queries
        if hasattr(user, "player_profile") and user.player_profile.team:
            return (
                Team.objects.select_related(
                    "sport", "head_coach__user", "assistant_coach__user"
                )
                .prefetch_related(
                    "players", "head_coach__sports", "assistant_coach__sports"
                )
                .filter(id=user.player_profile.team.id, is_active=True)
            )

        # User doesn't have appropriate role - deny access
        raise PermissionDenied("You don't have permission to access team data")

    def get_object(self):
        # Store the unfiltered queryset
        unfiltered_queryset = Team.objects.all()

        # Get the filtered queryset based on user role
        filtered_queryset = self.filter_queryset(self.get_queryset())

        # Get the lookup value from the URL
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs[lookup_url_kwarg]

        # Try to determine if the lookup value is a numeric ID
        try:
            is_numeric = lookup_value.isdigit()
        except (AttributeError, ValueError):
            is_numeric = False

        if is_numeric:
            # If it's numeric, look up by ID
            filter_kwargs = {"pk": lookup_value}
        else:
            # Otherwise, use slug
            filter_kwargs = {self.lookup_field: lookup_value}

        # First check if the object exists at all in the unfiltered queryset
        try:
            obj = unfiltered_queryset.get(**filter_kwargs)
        except Team.DoesNotExist:
            # If the team doesn't exist at all, raise 404
            from django.http import Http404

            raise Http404("Team does not exist")

        # Now check if the object is in the filtered queryset (user has access)
        if not filtered_queryset.filter(**filter_kwargs).exists():
            # If the team exists but user doesn't have access, raise permission denied
            raise PermissionDenied("You don't have permission to access this team")

        # Get the object from the filtered queryset
        obj = filtered_queryset.get(**filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        - GET requests are accessible to anyone
        - DELETE requests are restricted to admin users
        - POST/PUT requests can be done by admins or coaches
        - Coaches can modify their own teams
        """
        if self.action in ["create", "update", "destroy", "partial_update"]:
            permission_classes = [IsAdminOrCoachUser]
        elif self.action in ["my_team", "my_team_players", "my_teammates"]:
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = []

        return [permission() for permission in permission_classes]

    def perform_create(self, serializer):
        """
        When a coach creates a team, automatically assign the coach to the team
        """
        # If the requesting user is a coach, set them as the team's head coach
        if self.request.user.is_coach and hasattr(self.request.user, "coach_profile"):
            coach = self.request.user.coach_profile
            team = serializer.save(head_coach=coach)  # Direct assignment as head coach
        else:
            team = serializer.save()

        return team

    def perform_update(self, serializer):
        """Only allow coaches to update their own teams"""
        if self.request.user.is_admin:  # Admins can update any team
            serializer.save()
        elif self.request.user.is_coach and hasattr(self.request.user, "coach_profile"):
            # Coaches can only update their own teams
            coach = self.request.user.coach_profile
            # Get teams where this coach is either head coach or assistant coach (only active)
            coached_teams = Team.objects.filter(
                Q(head_coach=coach) | Q(assistant_coach=coach),
                is_active=True  # Only active teams for coaches
            )
            if serializer.instance in coached_teams:
                serializer.save()
            else:
                raise PermissionDenied("You can only update your own teams")

    def perform_destroy(self, instance):
        """Soft delete or hard delete team based on associated data"""
        if self.request.user.is_admin:  # Admins can delete any team
            if instance.has_associated_data():
                # Soft delete if team has associated games or trainings
                instance.soft_delete()
            else:
                # Hard delete if no associated data
                instance.delete()
        elif self.request.user.is_coach and hasattr(self.request.user, "coach_profile"):
            # Coaches can only delete their own teams
            coach = self.request.user.coach_profile
            # Get teams where this coach is either head coach or assistant coach (only active)
            coached_teams = Team.objects.filter(
                Q(head_coach=coach) | Q(assistant_coach=coach),
                is_active=True  # Only active teams for coaches
            )

            # Check if the team belongs to the coach
            if instance in coached_teams:
                if instance.has_associated_data():
                    # Soft delete if team has associated games or trainings
                    instance.soft_delete()
                else:
                    # Hard delete if no associated data
                    instance.delete()
            else:
                raise PermissionDenied("You can only delete your own teams")

    @action(detail=True, methods=["post"], permission_classes=[IsAdminOrCoachUser])
    def reactivate(self, request, **kwargs):
        """Reactivate a deactivated team"""
        team = self.get_object()
        
        if team.is_active:
            return Response(
                {"detail": "Team is already active."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        team.reactivate()
        serializer = self.get_serializer(team)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], permission_classes=[IsAdminUser])
    def coaches(self, request, **kwargs):
        team = self.get_object()
        coaches = []
        if team.head_coach:
            coaches.append(team.head_coach)
        if team.assistant_coach:
            coaches.append(team.assistant_coach)
        serializer = CoachInfoSerializer(
            coaches, many=True, context={"request": request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def players(self, request, **kwargs):
        team = self.get_object()
        players = team.players.select_related("user").all()
        serializer = PlayerInfoSerializer(
            players, many=True, context={"request": request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def analytics(self, request, **kwargs):
        team = self.get_object()

        # Time range filter (default to last 30 days)
        days = int(request.query_params.get("days", 30))
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # Games analytics
        all_games = Game.objects.filter(
            models.Q(home_team=team) | models.Q(away_team=team)
        )
        recent_games = all_games.filter(date__range=[start_date, end_date])

        # Calculate wins, losses, draws
        wins = 0
        losses = 0
        draws = 0

        for game in all_games.filter(status=Game.Status.COMPLETED):
            if game.winner_team == team:
                wins += 1
            elif game.winner_team is None:
                draws += 1
            else:
                losses += 1

        # Training analytics
        all_trainings = TrainingSession.objects.filter(team=team)
        recent_trainings = all_trainings.filter(
            date__range=[start_date.date(), end_date.date()]
        )

        # Player statistics
        total_players = team.players.count()

        analytics_data = {
            "total_games": all_games.count(),
            "recent_games": recent_games.count(),
            "total_wins": wins,
            "total_losses": losses,
            "total_draws": draws,
            "win_rate": round((wins / max(wins + losses + draws, 1)) * 100, 2),
            "total_trainings": all_trainings.count(),
            "recent_trainings": recent_trainings.count(),
            "total_players": total_players,
            "upcoming_games": all_games.filter(
                date__gte=timezone.now(),
                status__in=[Game.Status.SCHEDULED, Game.Status.POSTPONED],
            ).count(),
            "completed_games": all_games.filter(status=Game.Status.COMPLETED).count(),
            "training_completion_rate": self._calculate_training_completion_rate(team),
            "average_attendance": self._calculate_average_attendance(team),
            "time_range_days": days,
        }
        return Response(analytics_data)

    @action(detail=True, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def performance(self, request, **kwargs):
        team = self.get_object()

        # Time range filter (default to last 30 days)
        days = int(request.query_params.get("days", 30))
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # Get team games for performance analysis
        team_games = Game.objects.filter(
            models.Q(home_team=team) | models.Q(away_team=team),
            status=Game.Status.COMPLETED,
        )

        # Calculate performance metrics
        if team_games.exists():
            # Calculate average scores
            home_scores = (
                team_games.filter(home_team=team).aggregate(
                    avg_score=Avg("home_team_score")
                )["avg_score"]
                or 0
            )

            away_scores = (
                team_games.filter(away_team=team).aggregate(
                    avg_score=Avg("away_team_score")
                )["avg_score"]
                or 0
            )

            average_score = (
                (home_scores + away_scores) / 2 if (home_scores or away_scores) else 0
            )

            # Get highest scores
            highest_home_score = (
                team_games.filter(home_team=team).aggregate(
                    max_score=Max("home_team_score")
                )["max_score"]
                or 0
            )

            highest_away_score = (
                team_games.filter(away_team=team).aggregate(
                    max_score=Max("away_team_score")
                )["max_score"]
                or 0
            )

            highest_score = max(highest_home_score, highest_away_score)
        else:
            average_score = 0
            highest_score = 0

        # Training performance metrics
        completed_trainings = TrainingSession.objects.filter(
            team=team, status=TrainingSession.Status.COMPLETED
        )

        performance_data = {
            "average_team_score": round(average_score, 2),
            "highest_game_score": highest_score,
            "total_completed_games": team_games.count(),
            "total_completed_trainings": completed_trainings.count(),
            "recent_performance": self._get_recent_performance_trend(team, start_date),
            "training_effectiveness": self._calculate_training_effectiveness(team),
            "time_range_days": days,
        }
        return Response(performance_data)

    @action(detail=True, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def games(self, request, **kwargs):
        team = self.get_object()

        # Get all games for the team (both home and away)
        games = (
            Game.objects.filter(models.Q(home_team=team) | models.Q(away_team=team))
            .select_related("home_team", "away_team", "sport", "league", "season")
            .order_by("-date")
        )

        # Add pagination support
        page = self.paginate_queryset(games)
        if page is not None:
            serializer = GameSummarySerializer(
                page, many=True, context={"request": request, "team": team}
            )
            return self.get_paginated_response(serializer.data)

        serializer = GameSummarySerializer(
            games, many=True, context={"request": request, "team": team}
        )
        return Response(serializer.data)

    @action(detail=True, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def games_all(self, request, **kwargs):
        """
        Non-paginated endpoint to get all team games.
        Used by TeamDetails component for upcoming and recent games sections.
        """
        team = self.get_object()

        # Get all games for the team (both home and away)
        games = (
            Game.objects.filter(models.Q(home_team=team) | models.Q(away_team=team))
            .select_related("home_team", "away_team", "sport", "league", "season")
            .order_by("-date")
        )

        # No pagination - return all games
        serializer = GameSummarySerializer(
            games, many=True, context={"request": request, "team": team}
        )
        return Response(serializer.data)

    @action(detail=True, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def training_sessions(self, request, **kwargs):
        team = self.get_object()

        # Get all training sessions for the team
        trainings = (
            TrainingSession.objects.filter(team=team)
            .select_related("team")
            .prefetch_related("categories")
            .order_by("-date")
        )

        # Add pagination support
        page = self.paginate_queryset(trainings)
        if page is not None:
            serializer = TrainingSessionListSerializer(
                page, many=True, context={"request": request}
            )
            return self.get_paginated_response(serializer.data)

        serializer = TrainingSessionListSerializer(
            trainings, many=True, context={"request": request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def statistics(self, request, **kwargs):
        team = self.get_object()

        # Basic team statistics
        total_players = team.players.count()
        # Gender distribution (assuming User model has sex field)
        gender_stats = team.players.values("user__sex").annotate(count=Count("*"))

        gender_distribution = {"male": 0, "female": 0, "other": 0}
        for stat in gender_stats:
            sex = stat["user__sex"]
            count = stat["count"]
            if sex == "M":
                gender_distribution["male"] = count
            elif sex == "F":
                gender_distribution["female"] = count
            else:
                gender_distribution["other"] = count

        # Games statistics
        all_games = Game.objects.filter(
            models.Q(home_team=team) | models.Q(away_team=team)
        )

        # Calculate game results
        wins = losses = draws = 0
        for game in all_games.filter(status=Game.Status.COMPLETED):
            if game.winner_team == team:
                wins += 1
            elif game.winner_team is None:
                draws += 1
            else:
                losses += 1  # Training statistics
        training_stats = TrainingSession.objects.filter(team=team).aggregate(
            total_sessions=Count("id"),
            completed_sessions=Count(
                "id", filter=models.Q(status=TrainingSession.Status.COMPLETED)
            ),
            upcoming_sessions=Count(
                "id", filter=models.Q(status=TrainingSession.Status.UPCOMING)
            ),
        )

        statistics_data = {
            "total_players": total_players,
            "gender_distribution": gender_distribution,
            "games_statistics": {
                "total_games": all_games.count(),
                "wins": wins,
                "losses": losses,
                "draws": draws,
                "win_percentage": round(
                    (wins / max(wins + losses + draws, 1)) * 100, 2
                ),
            },
            "training_statistics": {
                "total_sessions": training_stats["total_sessions"] or 0,
                "completed_sessions": training_stats["completed_sessions"] or 0,
                "upcoming_sessions": training_stats["upcoming_sessions"] or 0,
                "completion_rate": round(
                    (
                        training_stats["completed_sessions"]
                        / max(training_stats["total_sessions"], 1)
                    )
                    * 100,
                    2,
                ),
            },
            "activity_summary": {
                "last_game": self._serialize_game(all_games.order_by("-date").first()),
                "next_game": self._serialize_game(
                    all_games.filter(
                        date__gte=timezone.now(), status=Game.Status.SCHEDULED
                    )
                    .order_by("date")
                    .first()
                ),
                "last_training": self._serialize_training(
                    TrainingSession.objects.filter(
                        team=team, status=TrainingSession.Status.COMPLETED
                    )
                    .order_by("-date")
                    .first()
                ),
                "next_training": self._serialize_training(
                    TrainingSession.objects.filter(
                        team=team, status=TrainingSession.Status.UPCOMING
                    )
                    .order_by("date")
                    .first()
                ),
            },
        }
        return Response(statistics_data)

    @action(detail=True, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def scoring_analytics(self, request, **kwargs):
        """Get scoring performance analytics for the team"""
        team = self.get_object()

        # Time range filter (default to last 30 days)
        days = int(request.query_params.get("days", 30))
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # Get completed games for the team
        team_games = Game.objects.filter(
            models.Q(home_team=team) | models.Q(away_team=team),
            status=Game.Status.COMPLETED,
            date__gte=start_date.date(),
        ).order_by("date")

        if not team_games.exists():
            return Response(
                {
                    "message": "No completed games found in the specified time range",
                    "scoring_data": [],
                    "summary": {
                        "total_games": 0,
                        "avg_points_scored": 0,
                        "avg_points_conceded": 0,
                        "avg_point_differential": 0,
                    },
                }
            )

        # Group games by week and calculate scoring metrics
        from collections import defaultdict
        from datetime import datetime

        weekly_data = defaultdict(
            lambda: {
                "total_scored": 0,
                "total_conceded": 0,
                "games_count": 0,
                "wins": 0,
            }
        )

        total_scored = 0
        total_conceded = 0
        total_games = 0

        for game in team_games:
            # Determine team's score and opponent's score
            if game.home_team == team:
                team_score = game.home_team_score or 0
                opponent_score = game.away_team_score or 0
            else:
                team_score = game.away_team_score or 0
                opponent_score = game.home_team_score or 0

            # Get week start (Monday) for proper weekly grouping
            game_date = game.date
            week_start = game_date - timedelta(days=game_date.weekday())
            week_key = f"Week of {week_start.strftime('%b %d')}"

            # Update weekly data
            weekly_data[week_key]["total_scored"] += team_score
            weekly_data[week_key]["total_conceded"] += opponent_score
            weekly_data[week_key]["games_count"] += 1

            # Count wins
            if team_score > opponent_score:
                weekly_data[week_key]["wins"] += 1

            # Update totals
            total_scored += team_score
            total_conceded += opponent_score
            total_games += 1

        # Convert to list format for frontend
        scoring_data = []
        for week, data in weekly_data.items():
            if data["games_count"] > 0:
                avg_scored = round(data["total_scored"] / data["games_count"], 1)
                avg_conceded = round(data["total_conceded"] / data["games_count"], 1)
                scoring_data.append(
                    {
                        "period": week,
                        "avg_points_scored": avg_scored,
                        "avg_points_conceded": avg_conceded,
                        "point_differential": round(avg_scored - avg_conceded, 1),
                        "games_played": data["games_count"],
                        "win_rate": round(
                            (data["wins"] / data["games_count"]) * 100, 1
                        ),
                    }
                )

        # Sort by date
        scoring_data.sort(
            key=lambda x: datetime.strptime(
                x["period"].replace("Week of ", ""), "%b %d"
            )
        )

        # Calculate summary statistics
        summary = {
            "total_games": total_games,
            "avg_points_scored": (
                round(total_scored / total_games, 1) if total_games > 0 else 0
            ),
            "avg_points_conceded": (
                round(total_conceded / total_games, 1) if total_games > 0 else 0
            ),
            "avg_point_differential": (
                round((total_scored - total_conceded) / total_games, 1)
                if total_games > 0
                else 0
            ),
            "time_range_days": days,
        }

        return Response({"scoring_data": scoring_data, "summary": summary})

    def _calculate_training_completion_rate(self, team):
        """Calculate the percentage of training sessions that were completed"""
        total_sessions = TrainingSession.objects.filter(team=team).count()
        completed_sessions = TrainingSession.objects.filter(
            team=team, status=TrainingSession.Status.COMPLETED
        ).count()

        if total_sessions == 0:
            return 0
        return round((completed_sessions / total_sessions) * 100, 2)

    def _calculate_average_attendance(self, team):
        """Calculate average attendance rate for training sessions"""
        from trainings.models import PlayerTraining

        completed_sessions = TrainingSession.objects.filter(
            team=team, status=TrainingSession.Status.COMPLETED
        )

        if not completed_sessions.exists():
            return 0

        total_expected_attendance = 0
        total_actual_attendance = 0

        for session in completed_sessions:
            expected = team.players.count()
            actual = PlayerTraining.objects.filter(
                session=session,
                attendance_status__in=[
                    "present",
                    "late",
                ],  # Count present and late as attended
            ).count()

            total_expected_attendance += expected
            total_actual_attendance += actual

        if total_expected_attendance == 0:
            return 0

        return round((total_actual_attendance / total_expected_attendance) * 100, 2)

    def _get_recent_performance_trend(self, team, start_date):
        """Get performance trend for recent games"""
        recent_games = Game.objects.filter(
            models.Q(home_team=team) | models.Q(away_team=team),
            date__gte=start_date,
            status=Game.Status.COMPLETED,
        ).order_by("date")

        trend_data = []
        for game in recent_games:
            if game.home_team == team:
                team_score = game.home_team_score or 0
                opponent_score = game.away_team_score or 0
            else:
                team_score = game.away_team_score or 0
                opponent_score = game.home_team_score or 0

            # Determine result based on scores first, then fall back to winner_team field
            if team_score > opponent_score:
                result = "win"
            elif team_score < opponent_score:
                result = "loss"
            elif team_score == opponent_score:
                result = "draw"
            else:
                # Fallback to winner_team field if scores are unclear
                result = (
                    "win"
                    if game.winner_team == team
                    else ("draw" if game.winner_team is None else "loss")
                )

            trend_data.append(
                {
                    "date": game.date.strftime("%Y-%m-%d"),
                    "team_score": team_score,
                    "opponent_score": opponent_score,
                    "result": result,
                }
            )

        return trend_data

    def _calculate_training_effectiveness(self, team):
        """Calculate training effectiveness based on completion and attendance"""
        completion_rate = self._calculate_training_completion_rate(team)
        attendance_rate = self._calculate_average_attendance(team)

        # Simple effectiveness score combining completion and attendance
        effectiveness = (completion_rate + attendance_rate) / 2
        return round(effectiveness, 2)

    def _serialize_game(self, game):
        """Serialize a Game object for JSON response"""
        if not game:
            return None

        return {
            "id": game.id,
            "home_team": game.home_team.name if game.home_team else None,
            "away_team": game.away_team.name if game.away_team else None,
            "home_team_score": game.home_team_score,
            "away_team_score": game.away_team_score,
            "date": game.date.isoformat() if game.date else None,
            "status": game.status,
            "sport": game.sport.name if game.sport else None,
            "winner_team": game.winner_team.name if game.winner_team else None,
        }

    def _serialize_training(self, training):
        """Serialize a TrainingSession object for JSON response"""
        if not training:
            return None

        return {
            "id": training.id,
            "title": training.title,
            "date": training.date.isoformat() if training.date else None,
            "start_time": (
                training.start_time.isoformat() if training.start_time else None
            ),
            "end_time": training.end_time.isoformat() if training.end_time else None,
            "status": training.status,
            "team": training.team.name if training.team else None,
        }


class SportTeamsViewSet(ReadOnlyModelViewSet):
    serializer_class = TeamSerializer
    lookup_field = "pk"
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["division"]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def get_queryset(self):
        sport_slug = self.kwargs["sport_slug"]
        user = self.request.user
        
        try:
            sport = Sport.objects.get(slug=sport_slug)
        except Sport.DoesNotExist:
            return Team.objects.none()  # Return empty queryset instead of Response
        
        # Base queryset filtered by sport
        base_queryset = Team.objects.filter(sport=sport)
        
        # Apply role-based filtering similar to TeamViewSet
        if user.is_authenticated and hasattr(user, "is_admin") and user.is_admin:
            # Admin: All teams in the sport
            return base_queryset.select_related(
                "sport", "head_coach__user", "assistant_coach__user"
            ).prefetch_related(
                "players", "head_coach__sports", "assistant_coach__sports"
            )
        
        if hasattr(user, "coach_profile"):
            # Coach: Only their active teams in the sport
            return base_queryset.filter(
                Q(head_coach=user.coach_profile) | Q(assistant_coach=user.coach_profile),
                is_active=True  # Only active teams for coaches
            ).select_related(
                "sport", "head_coach__user", "assistant_coach__user"
            ).prefetch_related(
                "players", "head_coach__sports", "assistant_coach__sports"
            )
        
        if hasattr(user, "player_profile") and user.player_profile.team:
            # Player: Only their own team if it's in this sport and active
            return base_queryset.filter(
                id=user.player_profile.team.id,
                is_active=True  # Only active teams for players
            )
        
        # User doesn't have appropriate role - return empty queryset
        return Team.objects.none()


class PlayerViews(ModelViewSet):
    queryset = Player.objects.all()
    serializer_class = PlayerInfoSerializer
    lookup_field = "slug"
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ["first_name", "last_name"]
    filterset_class = PlayerFilter
    pagination_class = Pagination

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def get_queryset(self):
        """
        Return players based on user role:
        - Admin: All players
        - Coach: Only players on their teams
        - Player: Only teammates
        - Others: Permission denied for all actions including list
        """
        user = self.request.user

        # Base queryset with annotations
        base_queryset = (
            Player.objects.select_related("user")
            .annotate(
                first_name=F("user__first_name"),
                last_name=F("user__last_name"),
                sex=F("user__sex"),
            )
            .order_by("user__first_name")
        )

        # For admins, show all players (including inactive users)
        if user.is_admin:
            return base_queryset
            
        # For non-admin users, only show players with active user accounts
        base_queryset = base_queryset.filter(user__is_active=True)
        
        # For coaches, show only active players from their teams
        if hasattr(user, "coach_profile"):
            coach = user.coach_profile
            # Get teams where this coach is either head coach or assistant coach
            coached_teams = Team.objects.filter(
                Q(head_coach=coach) | Q(assistant_coach=coach)
            )
            return base_queryset.filter(team__in=coached_teams)

        # For players, show only active teammates
        if hasattr(user, "player_profile") and user.player_profile.team:
            player_team = user.player_profile.team
            return base_queryset.filter(team=player_team)

        # User doesn't have appropriate role - deny access
        raise PermissionDenied("You don't have permission to access player data")

    def get_object(self):
        """
        Similar to TeamViewSet.get_object, this ensures players can only be accessed
        based on user role permissions
        """
        # Store the unfiltered queryset
        unfiltered_queryset = Player.objects.all()

        # Get the filtered queryset based on user role
        filtered_queryset = self.filter_queryset(self.get_queryset())

        # Get the lookup value from the URL
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs[lookup_url_kwarg]

        # Try to determine if the lookup value is a numeric ID
        try:
            is_numeric = lookup_value.isdigit()
        except (AttributeError, ValueError):
            is_numeric = False

        if is_numeric:
            # If it's numeric, look up by ID
            filter_kwargs = {"pk": lookup_value}
        else:
            # Otherwise, use slug
            filter_kwargs = {self.lookup_field: lookup_value}

        # First check if the object exists at all in the unfiltered queryset
        try:
            obj = unfiltered_queryset.get(**filter_kwargs)
        except Player.DoesNotExist:
            # If the player doesn't exist at all, raise 404
            from django.http import Http404

            raise Http404("Player does not exist")
        # Now check if the object is in the filtered queryset (user has access)
        if not filtered_queryset.filter(**filter_kwargs).exists():
            # If the player exists but user doesn't have access, raise permission denied
            raise PermissionDenied("You don't have permission to access this player")

        # Get the object from the filtered queryset
        obj = filtered_queryset.get(**filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        - GET requests are accessible to anyone with proper role (filtered by get_queryset)
        - POST/CREATE requests are restricted to admin users
        - DELETE/UPDATE requests can be done by admins or coaches (with team restrictions)
        - Coaches can only modify players from their own teams
        """
        if self.action in ["create", "update", "partial_update", "destroy"]:
            permission_classes = [IsAdminOrCoachUser]
        else:
            permission_classes = [IsAuthenticated]

        return [permission() for permission in permission_classes]

    def create(self, request, *args, **kwargs):
        """
        Override create to handle integrity errors and convert them to validation errors
        """
        from django.db import IntegrityError
        from rest_framework import status
        from rest_framework.response import Response

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            self.perform_create(serializer)
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
        except IntegrityError as e:
            # Handle jersey number uniqueness constraint
            if 'teams_player_team_id_jersey_number' in str(e):
                return Response(
                    {
                        'jersey_number': ['A player with this jersey number already exists in this team.']
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Handle other integrity errors
            elif 'unique constraint' in str(e).lower():
                return Response(
                    {
                        'non_field_errors': ['This combination of values already exists.']
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            else:
                # Re-raise if it's not a constraint violation we can handle
                raise

    def perform_update(self, serializer):
        """Only allow coaches to update players in their own teams"""
        if self.request.user.is_admin:  # Admins can update any player
            serializer.save()
        elif self.request.user.is_coach and hasattr(self.request.user, "coach_profile"):
            # Coaches can only update players from their teams (only active users)
            coach = self.request.user.coach_profile
            # Get teams where this coach is either head coach or assistant coach
            coached_teams = Team.objects.filter(
                Q(head_coach=coach) | Q(assistant_coach=coach)
            )
            player = serializer.instance

            # Make sure player has a team, that team is in coach's teams, and player user is active
            if (player.team and player.team in coached_teams and 
                player.user.is_active):
                serializer.save()
            else:
                raise PermissionDenied(
                    "You can only update active players from your own teams"
                )

    def update(self, request, *args, **kwargs):
        """
        Override update to handle integrity errors and convert them to validation errors
        """
        from django.db import IntegrityError
        from rest_framework import status
        from rest_framework.response import Response

        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        
        try:
            self.perform_update(serializer)
            if getattr(instance, '_prefetched_objects_cache', None):
                instance._prefetched_objects_cache = {}
            return Response(serializer.data)
        except IntegrityError as e:
            # Handle jersey number uniqueness constraint
            if 'teams_player_team_id_jersey_number' in str(e):
                return Response(
                    {
                        'jersey_number': ['A player with this jersey number already exists in this team.']
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Handle other integrity errors
            elif 'unique constraint' in str(e).lower():
                return Response(
                    {
                        'non_field_errors': ['This combination of values already exists.']
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            else:
                # Re-raise if it's not a constraint violation we can handle
                raise

    def perform_destroy(self, instance):
        """Soft delete or hard delete player based on associated data"""
        if self.request.user.is_admin:  # Admins can delete any player
            if instance.has_associated_data():
                # Soft delete if player has associated games or trainings
                instance.soft_delete()
            else:
                # Hard delete if no associated data
                instance.delete()
        elif self.request.user.is_coach and hasattr(self.request.user, "coach_profile"):
            # Coaches can only delete players from their teams (only active users)
            coach = self.request.user.coach_profile
            # Get teams where this coach is either head coach or assistant coach
            coached_teams = Team.objects.filter(
                Q(head_coach=coach) | Q(assistant_coach=coach)
            )
            player = instance

            # Make sure player has a team, that team is in coach's teams, and player user is active
            if (player.team and player.team in coached_teams and 
                player.user.is_active):
                if instance.has_associated_data():
                    # Soft delete if player has associated games or trainings
                    instance.soft_delete()
                else:
                    # Hard delete if no associated data
                    instance.delete()
            else:
                raise PermissionDenied(
                    "You can only delete active players from your own teams"
                )

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def reactivate(self, request, **kwargs):
        """Reactivate a soft-deleted player (admin only)"""
        player = self.get_object()
        
        if player.user.is_active:
            return Response(
                {"detail": "Player is already active."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        player.reactivate()
        
        # Return updated player data
        serializer = self.get_serializer(player)
        return Response(
            {
                "detail": "Player reactivated successfully.",
                "player": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class CoachViews(ModelViewSet):
    queryset = Coach.objects.all().prefetch_related("team_set")
    serializer_class = CoachInfoSerializer
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ["first_name", "last_name"]
    filterset_class = CoachFilter
    pagination_class = Pagination

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def get_queryset(self):
        """
        Return coaches based on user role:
        - Admin: All coaches (including inactive users)
        - Others: Only coaches with active user accounts
        """
        user = self.request.user
        
        base_queryset = Coach.objects.select_related("user").annotate(
            first_name=F("user__first_name"),
            last_name=F("user__last_name"),
            sex=F("user__sex"),
        )
        
        # For admins, show all coaches (including inactive users)
        if user.is_admin:
            return base_queryset
        
        # For non-admin users, only show coaches with active user accounts
        return base_queryset.filter(user__is_active=True)

    def perform_destroy(self, instance):
        """Soft delete or hard delete coach based on associated data"""
        if self.request.user.is_admin:  # Only admins can delete coaches
            if instance.has_associated_data():
                # Soft delete if coach has associated teams
                instance.soft_delete()
            else:
                # Hard delete if no associated data
                instance.delete()
        else:
            raise PermissionDenied("You don't have permission to delete coaches")

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def reactivate(self, request, **kwargs):
        """Reactivate a soft-deleted coach (admin only)"""
        coach = self.get_object()
        
        if coach.user.is_active:
            return Response(
                {"detail": "Coach is already active."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        coach.reactivate()
        
        # Return updated coach data
        serializer = self.get_serializer(coach)
        return Response(
            {
                "detail": "Coach reactivated successfully.",
                "coach": serializer.data,
            },
            status=status.HTTP_200_OK,
        )
