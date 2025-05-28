from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from sports_management.permissions import IsAdminUser, IsAdminOrCoachUser
from django.db.models import Count, Avg, Q, F
from django.utils import timezone
from datetime import timedelta
import logging

from teams.models import Team, Player, Coach
from games.models import Game
from trainings.models import TrainingSession, PlayerTraining, PlayerMetricRecord
from leagues.models import League
from sports.models import Sport
from users.models import User
from .serializers import (
    AdminOverviewSerializer,
    AdminAnalyticsSerializer,
    CoachOverviewSerializer,
    CoachPlayerProgressSerializer,
    PlayerOverviewSerializer,
    PlayerProgressDetailSerializer,
)

logger = logging.getLogger(__name__)


class DashboardViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"], permission_classes=[IsAdminUser])
    def admin_overview(self, request):
        """Complete system overview for admins"""
        # System-wide statistics
        total_teams = Team.objects.count()
        total_players = Player.objects.filter(
            team__isnull=False
        ).count()  # Only count players with teams
        total_coaches = Coach.objects.count()
        total_games = Game.objects.count()
        total_leagues = League.objects.count()
        total_sports = Sport.objects.count()

        # Recent activity (last 30 days)
        last_30_days = timezone.now() - timedelta(days=30)
        recent_games = Game.objects.filter(created_at__gte=last_30_days).count()
        recent_training_sessions = TrainingSession.objects.filter(
            date__gte=last_30_days.date()
        ).count()

        # Team distribution by sport
        teams_by_sport = (
            Team.objects.values("sport__name")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        # Player distribution by sport
        players_by_sport = (
            Player.objects.filter(
                team__isnull=False,  # Only include players with teams
                team__sport__isnull=False,  # Only include teams with sports
            )
            .values("team__sport__name")
            .annotate(count=Count("user"))
            .order_by("-count")
        )

        # Recent registrations (players assigned to teams)
        recent_players = Player.objects.filter(
            user__date_joined__gte=last_30_days,
            team__isnull=False,  # Only count players with teams
        ).count()

        # Games by status
        games_by_status = Game.objects.values("status").annotate(count=Count("id"))

        data = {
            "system_overview": {
                "total_teams": total_teams,
                "total_players": total_players,
                "total_coaches": total_coaches,
                "total_games": total_games,
                "total_leagues": total_leagues,
                "total_sports": total_sports,
            },
            "recent_activity": {
                "recent_games": recent_games,
                "recent_training_sessions": recent_training_sessions,
                "recent_player_registrations": recent_players,
            },
            "distribution_stats": {
                "teams_by_sport": list(teams_by_sport),
                "players_by_sport": list(players_by_sport),
                "games_by_status": list(games_by_status),
            },
        }

        serializer = AdminOverviewSerializer(data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], permission_classes=[IsAdminUser])
    def admin_analytics(self, request):
        """Advanced analytics for admins"""
        # Training attendance analytics across all teams
        total_training_records = PlayerTraining.objects.count()
        overall_attendance_rate = 0
        if total_training_records > 0:
            present_count = PlayerTraining.objects.filter(
                attendance_status="present"
            ).count()
            overall_attendance_rate = (present_count / total_training_records) * 100

        # Game completion status
        completed_games = Game.objects.filter(status="completed").count()
        upcoming_games = Game.objects.filter(status="scheduled").count()
        in_progress_games = Game.objects.filter(status="in_progress").count()

        # Top teams by wins (simplified calculation)
        teams_with_wins = []
        for team in Team.objects.all()[:10]:  # Limit to top 10
            wins, losses = team.win_loss_record()
            teams_with_wins.append(
                {
                    "team_name": team.name,
                    "wins": wins,
                    "losses": losses,
                    "win_rate": round(
                        (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0, 2
                    ),
                }
            )
        # Sort by win rate
        teams_with_wins.sort(key=lambda x: x["win_rate"], reverse=True)

        # Active coaches and their teams
        active_coaches = Coach.objects.annotate(team_count=Count("teams")).order_by(
            "-team_count"
        )[:10]

        coach_stats = [
            {"coach_name": coach.user.get_full_name(), "team_count": coach.team_count}
            for coach in active_coaches
        ]

        data = {
            "training_analytics": {
                "total_training_records": total_training_records,
                "overall_attendance_rate": round(overall_attendance_rate, 2),
            },
            "game_analytics": {
                "completed_games": completed_games,
                "upcoming_games": upcoming_games,
                "in_progress_games": in_progress_games,
            },
            "top_teams": teams_with_wins[:6],
            "coach_statistics": coach_stats,
        }

        serializer = AdminAnalyticsSerializer(data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def coach_overview(self, request):
        """Team-focused dashboard for coaches"""
        user = request.user

        try:
            if not hasattr(user, "coach_profile"):
                return Response(
                    {"error": "Coach profile not found"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            coach_teams = user.coach_profile.teams.all()

            # Team statistics
            total_teams = coach_teams.count()
            total_players = Player.objects.filter(team__in=coach_teams).count()

            # Training statistics (last 30 days)
            last_30_days = timezone.now() - timedelta(days=30)
            recent_training_sessions = TrainingSession.objects.filter(
                team__in=coach_teams, date__gte=last_30_days.date()
            ).count()

            # Attendance analytics for coach's teams
            team_attendance_data = []
            for team in coach_teams:
                team_training_records = PlayerTraining.objects.filter(
                    session__team=team, session__date__gte=last_30_days.date()
                )
                total_records = team_training_records.count()
                present_records = team_training_records.filter(
                    attendance_status="present"
                ).count()
                attendance_rate = (
                    (present_records / total_records * 100) if total_records > 0 else 0
                )

                team_attendance_data.append(
                    {
                        "team_name": team.name,
                        "team_id": team.id,
                        "attendance_rate": round(attendance_rate, 2),
                        "total_sessions": team_training_records.values("session")
                        .distinct()
                        .count(),
                        "total_players": team.players.count(),
                    }
                )

            # Upcoming games for coach's teams
            upcoming_games = (
                Game.objects.filter(
                    Q(home_team__in=coach_teams) | Q(away_team__in=coach_teams),
                    status="scheduled",
                )
                .filter(date__gte=timezone.now())
                .order_by("date")[:6]
            )

            upcoming_games_data = [
                {
                    "id": game.id,
                    "home_team": game.home_team.name,
                    "away_team": game.away_team.name,
                    "date": game.date,
                    "location": game.location,
                    "is_home": game.home_team in coach_teams,
                }
                for game in upcoming_games
            ]

            # Recent training sessions
            recent_sessions = TrainingSession.objects.filter(
                team__in=coach_teams, date__gte=last_30_days.date()
            ).order_by("-date")[:6]

            recent_sessions_data = [
                {
                    "id": session.id,
                    "title": session.title,
                    "date": session.date,
                    "team": session.team.name,
                    "attendance_count": session.player_records.filter(
                        attendance_status="present"
                    ).count(),
                    "total_players": session.player_records.count(),
                }
                for session in recent_sessions
            ]

            response_data = {
                "team_overview": {
                    "total_teams": total_teams,
                    "total_players": total_players,
                    "recent_training_sessions": recent_training_sessions,
                },
                "team_attendance": team_attendance_data,
                "upcoming_games": upcoming_games_data,
                "recent_training_sessions": recent_sessions_data,
            }

            serializer = CoachOverviewSerializer(response_data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error in coach_overview: {str(e)}")
            return Response(
                {"error": "An error occurred while fetching coach overview data"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def coach_player_progress(self, request):
        """Player progress analytics for coaches"""
        user = request.user

        if not hasattr(user, "coach_profile"):
            return Response({"error": "Coach profile not found"}, status=400)

        coach_teams = user.coach_profile.teams.all()
        players = Player.objects.filter(team__in=coach_teams)        # Get player progress data
        player_progress_data = []
        last_30_days = timezone.now() - timedelta(days=30)

        for player in players[:15]:  # Limit to top 15 for dashboard
            # Get recent training records
            recent_training_records = PlayerTraining.objects.filter(
                player=player, session__date__gte=last_30_days.date()
            )

            # Get recent metric records
            recent_metrics = PlayerMetricRecord.objects.filter(
                player_training__player=player, recorded_at__gte=last_30_days
            ).order_by("-recorded_at")

            # Calculate attendance rate
            total_sessions = recent_training_records.count()
            attended_sessions = recent_training_records.filter(
                attendance_status="present"
            ).count()
            attendance_rate = (
                (attended_sessions / total_sessions * 100) if total_sessions > 0 else 0
            )            # Calculate performance improvements
            overall_improvement = self._calculate_overall_improvement(player)
            recent_improvement = self._calculate_recent_improvement(player, last_30_days)

            player_progress_data.append(
                {
                    "player_id": player.user_id,
                    "player_name": player.user.get_full_name(),
                    "team": player.team.name if player.team else "No Team",
                    "jersey_number": player.jersey_number,
                    "recent_metrics_count": recent_metrics.count(),
                    "attendance_rate": round(attendance_rate, 2),
                    "total_sessions": total_sessions,
                    "last_training_date": (
                        recent_training_records.order_by("-session__date")
                        .first()
                        .session.date
                        if recent_training_records.exists()
                        else None
                    ),
                    "overall_improvement": overall_improvement,
                    "recent_improvement": recent_improvement,
                }
            )

        data = {"player_progress": player_progress_data}

        serializer = CoachPlayerProgressSerializer(data)
        return Response(serializer.data)

    def _calculate_overall_improvement(self, player):
        """Calculate overall improvement across all metrics for a player"""
        from trainings.services.progress_service import ProgressService
        
        return ProgressService.calculate_overall_improvement(player)

    def _calculate_recent_improvement(self, player, last_30_days):
        """Calculate recent improvement for a player in the last 30 days"""
        from trainings.services.progress_service import ProgressService
        
        # Convert last_30_days datetime to date if needed
        start_date = last_30_days.date() if hasattr(last_30_days, 'date') else last_30_days
        
        return ProgressService.calculate_recent_improvement(player, date_from=start_date)

    @action(detail=False, methods=["get"])
    def player_overview(self, request):
        """Personal dashboard for players"""
        user = request.user

        try:
            if not hasattr(user, "player_profile"):
                return Response(
                    {"error": "Player profile not found"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            player = user.player_profile

            # Personal training statistics (last 30 days)
            last_30_days = timezone.now() - timedelta(days=30)
            player_training_records = PlayerTraining.objects.filter(
                player=player, session__date__gte=last_30_days.date()
            )

            total_sessions = player_training_records.count()
            attended_sessions = player_training_records.filter(
                attendance_status="present"
            ).count()
            attendance_rate = (
                (attended_sessions / total_sessions * 100) if total_sessions > 0 else 0
            )

            # Upcoming training sessions
            upcoming_sessions = []
            if player.team:
                upcoming_sessions = TrainingSession.objects.filter(
                    team=player.team, date__gte=timezone.now().date()
                ).order_by("date")[:6]

            upcoming_sessions_data = [
                {
                    "id": session.id,
                    "title": session.title,
                    "date": session.date,
                    "start_time": session.start_time,
                    "location": session.location,
                }
                for session in upcoming_sessions
            ]

            # Upcoming games for player's team
            upcoming_games = []
            if player.team:
                upcoming_games = (
                    Game.objects.filter(
                        Q(home_team=player.team) | Q(away_team=player.team),
                        status="scheduled",
                    )
                    .filter(date__gte=timezone.now())
                    .order_by("date")[:6]
                )

            upcoming_games_data = [
                {
                    "id": game.id,
                    "home_team": game.home_team.name,
                    "away_team": game.away_team.name,
                    "date": game.date,
                    "location": game.location,
                    "is_home": game.home_team == player.team,
                }
                for game in upcoming_games
            ]

            # Recent performance metrics
            recent_metrics = PlayerMetricRecord.objects.filter(
                player_training__player=player
            ).order_by("-recorded_at")[:10]

            recent_metrics_data = [
                {
                    "metric_name": record.metric.name,
                    "value": float(record.value),
                    "unit": record.metric.metric_unit.code,
                    "recorded_at": record.recorded_at,
                    "session_date": record.player_training.session.date,
                }
                for record in recent_metrics
            ]

            # Team information
            team_info = None
            if player.team:
                team_info = {
                    "name": player.team.name,
                    "sport": player.team.sport.name,
                    "total_players": player.team.players.count(),
                    "coach": (
                        player.team.coach.user.get_full_name()
                        if player.team.coach
                        else "No Coach"
                    ),
                }
            # Player positions
            positions = list(player.position.values_list("name", flat=True))

            response_data = {
                "personal_stats": {
                    "attendance_rate": round(attendance_rate, 2),
                    "total_sessions_last_30_days": total_sessions,
                    "attended_sessions": attended_sessions,
                    "jersey_number": player.jersey_number,
                    "positions": positions,
                    "height": float(player.height) if player.height else None,
                    "weight": float(player.weight) if player.weight else None,
                },
                "upcoming_sessions": upcoming_sessions_data,
                "upcoming_games": upcoming_games_data,
                "recent_metrics": recent_metrics_data,
                "team_info": team_info,
            }

            serializer = PlayerOverviewSerializer(response_data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error in player_overview: {str(e)}")
            return Response(
                {"error": "An error occurred while fetching player overview data"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"])
    def player_progress(self, request):
        """Personal progress tracking for players"""
        user = request.user

        if not hasattr(user, "player_profile"):
            return Response({"error": "Player profile not found"}, status=400)

        player = user.player_profile

        # Get progress data for different time periods
        time_periods = {
            "last_week": timezone.now() - timedelta(days=7),
            "last_month": timezone.now() - timedelta(days=30),
            "last_3_months": timezone.now() - timedelta(days=90),
        }

        progress_data = {}
        for period_name, start_date in time_periods.items():
            metrics = PlayerMetricRecord.objects.filter(
                player_training__player=player, recorded_at__gte=start_date
            ).order_by("metric__name", "recorded_at")

            training_sessions = PlayerTraining.objects.filter(
                player=player, session__date__gte=start_date.date()
            )

            progress_data[period_name] = {
                "total_metrics_recorded": metrics.count(),
                "unique_metrics": metrics.values("metric__name").distinct().count(),
                "training_sessions_attended": training_sessions.filter(
                    attendance_status="present"
                ).count(),
                "total_training_sessions": training_sessions.count(),
            }
        # Get metric trends (last 10 records for each metric)
        metric_trends = {}
        unique_metrics = (
            PlayerMetricRecord.objects.filter(player_training__player=player)
            .values_list("metric__name", flat=True)
            .distinct()
        )

        for metric_name in unique_metrics:
            recent_records = PlayerMetricRecord.objects.filter(
                player_training__player=player, metric__name=metric_name
            ).order_by("-recorded_at")[:10]

            metric_trends[metric_name] = [
                {
                    "value": float(record.value),
                    "date": record.player_training.session.date,
                    "unit": record.metric.metric_unit.code,
                }
                for record in reversed(recent_records)
            ]

        data = {"progress_summary": progress_data, "metric_trends": metric_trends}

        serializer = PlayerProgressDetailSerializer(data)
        return Response(serializer.data)
