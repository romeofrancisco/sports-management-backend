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
    DashboardSummarySerializer,
    TrainingSummarySerializer,
    LeagueSummarySerializer,
    GameSummarySerializer,
    AnalyticsSerializer,
    ChartDataSerializer,
)
from .services import (
    DashboardSummaryService,
    TrainingSummaryService,
    LeagueSummaryService,
    GameSummaryService,
    AnalyticsService,
)
from trainings.services.attendance_analytics_service import (
    AttendanceAnalyticsService,
)

logger = logging.getLogger(__name__)


class DashboardViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"], permission_classes=[IsAdminUser])
    def admin_overview(self, request):
        """Complete system overview for admins with meaningful metrics"""
        try:
            # System-wide statistics
            total_teams = Team.objects.count()
            total_players = Player.objects.filter(team__isnull=False, user__is_active=True).count()
            total_coaches = Coach.objects.count()
            total_games = Game.objects.count()
            total_leagues = League.objects.count()
            total_sports = Sport.objects.count()
            # Users without teams (important for admin to track)
            unassigned_players = Player.objects.filter(team__isnull=True).count()
            coaches_without_teams = (
                Coach.objects.annotate(
                    team_count=Count("head_coached_teams")
                    + Count("assistant_coached_teams")
                )
                .filter(team_count=0)
                .count()
            )

            # Time-based activity analysis
            last_30_days = timezone.now() - timedelta(days=30)
            last_7_days = timezone.now() - timedelta(days=7)
            last_24_hours = timezone.now() - timedelta(hours=24)

            # Active users (logged in recently)
            active_users_today = User.objects.filter(
                last_login__gte=last_24_hours
            ).count()
            active_users_week = User.objects.filter(last_login__gte=last_7_days).count()

            # Recent meaningful activity
            games_this_month = Game.objects.filter(
                date__gte=last_30_days.date()
            ).count()
            completed_games_month = Game.objects.filter(
                date__gte=last_30_days.date(), status="completed"
            ).count()
            training_sessions_month = TrainingSession.objects.filter(
                date__gte=last_30_days.date()
            ).count()

            # New registrations with better context
            new_users_month = User.objects.filter(date_joined__gte=last_30_days).count()
            new_users_week = User.objects.filter(date_joined__gte=last_7_days).count()

            # System health metrics
            teams_without_coaches = Team.objects.filter(
                head_coach__isnull=True, assistant_coach__isnull=True
            ).count()
            teams_with_few_players = (
                Team.objects.annotate(player_count=Count("players"))
                .filter(player_count__lt=F('sport__max_players_on_field'))
                .count()
            )

            # Engagement metrics
            games_scheduled = Game.objects.filter(
                status="scheduled", date__gte=timezone.now().date()
            ).count()

            upcoming_trainings = TrainingSession.objects.filter(
                status="upcoming"
            ).count()

            # Distribution statistics with more detail
            teams_by_sport = list(
                Team.objects.values("sport__name", "sport__id")
                .annotate(
                    team_count=Count("id", distinct=True),
                    active_players=Count("players", distinct=True),
                    total_coaches=Count("head_coach", distinct=True)
                    + Count("assistant_coach", distinct=True),
                )
                .order_by("-team_count")
            )

            players_by_sport = list(
                Player.objects.filter(team__isnull=False, team__sport__isnull=False)
                .values("team__sport__name", "team__sport__id")
                .annotate(count=Count("user"))
                .order_by("-count")
            )

            # Gender-based statistics
            male_players = Player.objects.filter(
                team__isnull=False, user__sex="male"
            ).count()
            female_players = Player.objects.filter(
                team__isnull=False, user__sex="female"
            ).count()

            male_teams = Team.objects.filter(division="male").count()
            female_teams = Team.objects.filter(division="female").count()

            # Players by gender and sport
            players_by_gender_sport = list(
                Player.objects.filter(team__isnull=False, team__sport__isnull=False)
                .values("team__sport__name", "user__sex")
                .annotate(count=Count("user"))
                .order_by("team__sport__name", "user__sex")
            )

            # Teams by division and sport
            teams_by_division_sport = list(
                Team.objects.values("sport__name", "division")
                .annotate(count=Count("id"))
                .order_by("sport__name", "division")
            )  # League activity summary
            active_leagues = League.objects.annotate(
                active_seasons=Count("seasons", filter=Q(seasons__status="ongoing")),
                total_teams=Count("seasons__teams", distinct=True),
            ).filter(active_seasons__gt=0)

            league_summary = [
                {
                    "id": league.id,
                    "name": league.name,
                    "sport": league.sport.name,
                    "active_seasons": league.active_seasons,
                    "total_teams": league.total_teams,
                }
                for league in active_leagues[:5]
            ]  # Performance indicators
            avg_players_per_team = (
                Team.objects.annotate(player_count=Count("players")).aggregate(
                    avg_players=Avg("player_count")
                )["avg_players"]
                or 0
            )

            # System Performance Summary calculations for frontend
            # Training engagement analytics
            total_training_records = PlayerTraining.objects.count()
            training_attendance_rate = 0
            if total_training_records > 0:
                present_count = PlayerTraining.objects.filter(
                    attendance_status="present"
                ).count()
                training_attendance_rate = (
                    present_count / total_training_records
                ) * 100

            # Team utilization metrics
            teams_active_last_month = (
                Team.objects.filter(
                    Q(training_sessions__date__gte=last_30_days.date())
                    | Q(home_games__date__gte=last_30_days.date())
                    | Q(away_games__date__gte=last_30_days.date())
                )
                .distinct()
                .count()
            )
            team_utilization_rate = (
                (teams_active_last_month / total_teams * 100) if total_teams > 0 else 0
            )

            # League health metrics
            leagues_with_active_seasons = (
                League.objects.filter(seasons__status__in=["ongoing", "upcoming"])
                .distinct()
                .count()
            )
            league_activity_rate = (
                (leagues_with_active_seasons / total_leagues * 100)
                if total_leagues > 0
                else 0
            )

            # System health score calculation
            system_health_score = self._calculate_system_health_score()

            # Calculate summary counts for insights
            warnings_count = (
                (1 if teams_without_coaches > 0 else 0)
                + (1 if teams_with_few_players > 0 else 0)
                + (1 if unassigned_players > 0 else 0)
                + (1 if training_attendance_rate < 70 else 0)
            )
            successes_count = (
                (1 if system_health_score >= 80 else 0)
                + (1 if league_activity_rate >= 75 else 0)
                + (1 if team_utilization_rate >= 60 else 0)
            )

            data = {
                "system_overview": {
                    "total_teams": total_teams,
                    "total_players": total_players,
                    "total_coaches": total_coaches,
                    "total_games": total_games,
                    "total_leagues": total_leagues,
                    "total_sports": total_sports,
                    "unassigned_players": unassigned_players,
                    "coaches_without_teams": coaches_without_teams,
                    "avg_players_per_team": round(avg_players_per_team, 1),
                },
                "user_activity": {
                    "active_users_today": active_users_today,
                    "active_users_week": active_users_week,
                    "new_users_month": new_users_month,
                    "new_users_week": new_users_week,
                },
                "recent_activity": {
                    "games_this_month": games_this_month,
                    "completed_games_month": completed_games_month,
                    "training_sessions_month": training_sessions_month,
                    "games_scheduled": games_scheduled,
                    "upcoming_trainings": upcoming_trainings,
                },
                "system_health": {
                    "teams_without_coaches": teams_without_coaches,
                    "teams_with_few_players": teams_with_few_players,
                    "unassigned_players": unassigned_players,
                },
                "distribution_stats": {
                    "teams_by_sport": teams_by_sport,
                    "players_by_sport": players_by_sport,
                    "active_leagues": league_summary,
                    "gender_stats": {
                        "male_players": male_players,
                        "female_players": female_players,
                        "male_teams": male_teams,
                        "female_teams": female_teams,
                        "players_by_gender_sport": players_by_gender_sport,
                        "teams_by_division_sport": teams_by_division_sport,
                    },
                },
                # Analytics data for System Performance Summary
                "analytics": {
                    "training_analytics": {
                        "overall_attendance_rate": round(training_attendance_rate, 2),
                        "training_trend": "stable",
                        "monthly_trend": self._build_monthly_trend(request),
                    },
                    "performance_analytics": {
                        "team_utilization_rate": round(team_utilization_rate, 2)
                    },
                    "system_health": {
                        "league_activity_rate": round(league_activity_rate, 2)
                    },
                },
                # Insights data for System Performance Summary
                "insights": {
                    "system_health_score": round(system_health_score, 0),
                    "summary": {
                        "warnings": warnings_count,
                        "successes": successes_count,
                    },
                },
            }

            serializer = AdminOverviewSerializer(data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error in admin_overview: {str(e)}")
            return Response(
                {"error": "An error occurred while fetching admin overview data"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAdminUser])
    def admin_analytics(self, request):
        """Advanced analytics for admins with actionable insights"""
        try:
            last_30_days = timezone.now() - timedelta(days=30)
            last_90_days = timezone.now() - timedelta(days=90)

            # Training engagement analytics
            total_training_records = PlayerTraining.objects.count()
            training_attendance_rate = 0
            if total_training_records > 0:
                present_count = PlayerTraining.objects.filter(
                    attendance_status="present"
                ).count()
                training_attendance_rate = (
                    present_count / total_training_records
                ) * 100

            # Monthly training trends
            monthly_training_sessions = TrainingSession.objects.filter(
                date__gte=last_30_days.date()
            ).count()

            previous_month_sessions = TrainingSession.objects.filter(
                date__gte=(timezone.now() - timedelta(days=60)).date(),
                date__lt=last_30_days.date(),
            ).count()

            training_trend = "stable"
            if previous_month_sessions > 0:
                trend_percentage = (
                    (monthly_training_sessions - previous_month_sessions)
                    / previous_month_sessions
                ) * 100
                if trend_percentage > 10:
                    training_trend = "increasing"
                elif trend_percentage < -10:
                    training_trend = "decreasing"

            # Game completion and scheduling analytics
            completed_games = Game.objects.filter(status="completed").count()
            scheduled_games = Game.objects.filter(status="scheduled").count()
            in_progress_games = Game.objects.filter(status="in_progress").count()

            # Games completion rate in last 30 days
            recent_games = Game.objects.filter(date__gte=last_30_days.date())
            recent_completed = recent_games.filter(status="completed").count()
            recent_total = recent_games.count()
            completion_rate = (
                (recent_completed / recent_total * 100) if recent_total > 0 else 0
            )

            # Team performance analytics
            top_performing_teams = []
            teams_with_stats = Team.objects.annotate(
                games_played=Count(
                    "home_games", filter=Q(home_games__status="completed")
                )
                + Count("away_games", filter=Q(away_games__status="completed")),
                recent_games=Count(
                    "home_games", filter=Q(home_games__date__gte=last_30_days.date())
                )
                + Count(
                    "away_games", filter=Q(away_games__date__gte=last_30_days.date())
                ),
            ).filter(games_played__gt=0)[:10]

            for team in teams_with_stats:
                wins, losses = team.win_loss_record()
                if wins + losses > 0:
                    top_performing_teams.append(
                        {
                            "team_id": team.id,
                            "team_name": team.name,
                            "sport": team.sport.name if team.sport else "No Sport",
                            "wins": wins,
                            "losses": losses,
                            "games_played": wins + losses,
                            "win_rate": round((wins / (wins + losses) * 100), 2),
                            "recent_activity": team.recent_games,
                        }
                    )

            top_performing_teams.sort(
                key=lambda x: (x["win_rate"], x["games_played"]), reverse=True
            )

            # Coach effectiveness analytics
            coach_analytics = []
            # Get coaches that have teams (either as head coach or assistant coach)
            active_coaches = Coach.objects.filter(
                Q(head_coached_teams__isnull=False)
                | Q(assistant_coached_teams__isnull=False)
            ).distinct()[:10]
            for coach in active_coaches:
                # Get teams where this coach is either head coach or assistant coach
                coach_teams = Team.objects.filter(
                    Q(head_coach=coach) | Q(assistant_coach=coach)
                )

                # Calculate metrics manually
                team_count = coach_teams.count()
                total_players = Player.objects.filter(team__in=coach_teams).count()
                recent_trainings = TrainingSession.objects.filter(
                    team__in=coach_teams, date__gte=last_30_days.date()
                ).count()

                # Skip coaches with no teams
                if team_count == 0:
                    continue

                # Calculate average attendance for coach's teams
                coach_training_records = PlayerTraining.objects.filter(
                    session__team__in=coach_teams,
                    session__date__gte=last_30_days.date(),
                )
                total_records = coach_training_records.count()
                present_records = coach_training_records.filter(
                    attendance_status="present"
                ).count()
                attendance_rate = (
                    (present_records / total_records * 100) if total_records > 0 else 0
                )

                # Calculate effectiveness score with improved formula
                base_score = attendance_rate * 0.6  # 60% weight on attendance
                
                # Training frequency score (normalized to 0-40 scale)
                # Ideal: 8-12 sessions per month (2-3 per week)
                training_frequency_score = 0
                if recent_trainings >= 8:
                    training_frequency_score = min(40, recent_trainings * 3.33)  # Cap at 40
                elif recent_trainings >= 4:
                    training_frequency_score = recent_trainings * 5  # 4-7 sessions
                else:
                    training_frequency_score = recent_trainings * 2.5  # Penalty for too few
                
                # Team engagement bonus (if managing multiple teams effectively)
                engagement_bonus = 0
                if team_count > 1 and attendance_rate >= 70:
                    engagement_bonus = min(10, team_count * 2)  # Max 10 points bonus
                
                # Calculate final effectiveness score
                effectiveness_score = base_score + training_frequency_score + engagement_bonus
                effectiveness_score = max(0, min(100, effectiveness_score))  # Ensure 0-100 range

                coach_analytics.append(
                    {
                        "coach_id": coach.user.id,
                        "coach_name": coach.user.get_full_name(),
                        "team_count": team_count,
                        "total_players": total_players,
                        "recent_trainings": recent_trainings,
                        "attendance_rate": round(attendance_rate, 2),
                        "effectiveness_score": round(effectiveness_score, 2),
                    }
                )

            coach_analytics.sort(key=lambda x: x["effectiveness_score"], reverse=True)

            # System utilization metrics
            teams_active_last_month = (
                Team.objects.filter(
                    Q(training_sessions__date__gte=last_30_days.date())
                    | Q(home_games__date__gte=last_30_days.date())
                    | Q(away_games__date__gte=last_30_days.date())
                )
                .distinct()
                .count()
            )

            total_teams = Team.objects.count()
            team_utilization_rate = (
                (teams_active_last_month / total_teams * 100) if total_teams > 0 else 0
            )

            # Player engagement metrics
            active_players = (
                Player.objects.filter(
                    training_records__session__date__gte=last_30_days.date()
                )
                .distinct()
                .count()
            )

            # League health metrics
            leagues_with_active_seasons = (
                League.objects.filter(seasons__status__in=["ongoing", "upcoming"])
                .distinct()
                .count()
            )

            total_leagues = League.objects.count()
            league_activity_rate = (
                (leagues_with_active_seasons / total_leagues * 100)
                if total_leagues > 0
                else 0
            )

            # Growth metrics
            teams_created_month = Team.objects.filter(
                created_at__gte=last_30_days
            ).count()

            players_joined_month = Player.objects.filter(
                user__date_joined__gte=last_30_days
            ).count()

            data = {
                "training_analytics": {
                    "total_training_records": total_training_records,
                    "overall_attendance_rate": round(training_attendance_rate, 2),
                    "monthly_sessions": monthly_training_sessions,
                    "training_trend": training_trend,
                    "active_players_month": active_players,
                    # Add monthly trend data for charts (labels and values)
                    "monthly_trend": self._build_monthly_trend(request),
                },
                "game_analytics": {
                    "completed_games": completed_games,
                    "scheduled_games": scheduled_games,
                    "in_progress_games": in_progress_games,
                    "completion_rate_month": round(completion_rate, 2),
                    "recent_games_total": recent_total,
                },
                "performance_analytics": {
                    "top_teams": top_performing_teams[:8],
                    "team_utilization_rate": round(team_utilization_rate, 2),
                    "teams_active_month": teams_active_last_month,
                },
                "coach_analytics": coach_analytics[:6],
                "system_health": {
                    "league_activity_rate": round(league_activity_rate, 2),
                    "active_leagues": leagues_with_active_seasons,
                    "total_leagues": total_leagues,
                },
                "growth_metrics": {
                    "new_teams_month": teams_created_month,
                    "new_players_month": players_joined_month,
                    "growth_trend": "stable",  # Could be calculated based on historical data
                },
            }

            serializer = AdminAnalyticsSerializer(data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error in admin_analytics: {str(e)}")
            return Response(
                {"error": "An error occurred while fetching admin analytics data"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _build_monthly_trend(self, request, months=6):
        """Helper to build monthly labels and values for charts using AttendanceAnalyticsService

        Returns: { labels: [...], values: [...] }
        """
        try:
            # Prefer session-based counts to ensure the chart has values even when
            # attendance records (PlayerTraining) are sparse or missing.
            from trainings.models import TrainingSession
            from django.utils import timezone
            from dateutil.relativedelta import relativedelta

            now = timezone.now().date()
            labels = []
            values = []

            # Build last `months` months labels and counts (oldest -> newest)
            for i in range(months - 1, -1, -1):
                month_date = (now - relativedelta(months=i)).replace(day=1)
                month_label = month_date.strftime("%b %Y")
                # Count training sessions within this month
                start = month_date
                # end is first day of next month
                end = (month_date + relativedelta(months=1))
                count = (
                    TrainingSession.objects.filter(date__gte=start, date__lt=end)
                    .count()
                )
                labels.append(month_label)
                values.append(count)

            return {"labels": labels, "values": values}
        except Exception as e:
            logger.exception(f"Error building monthly trend: {e}")
            return {"labels": [], "values": []}

    @action(detail=False, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def coach_overview(self, request):
        """Team-focused dashboard for coaches - also supports admin access to specific coach data"""
        user = request.user
        coach_id = request.query_params.get("coach_id")

        try:
            # Import models at the beginning
            from teams.models import Coach, Team, Player
            from games.models import Game
            from trainings.models import TrainingSession, PlayerTraining

            # If coach_id is provided, check if user has permission to view other coaches
            if coach_id:
                # Admin users can view any coach
                if user.role == "Admin":
                    try:
                        coach = Coach.objects.get(user_id=coach_id)
                    except Coach.DoesNotExist:
                        return Response(
                            {"error": "Coach not found"},
                            status=status.HTTP_404_NOT_FOUND,
                        )
                else:
                    return Response(
                        {"error": "Permission denied"},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            else:
                # Default behavior - get current user's coach profile
                if not hasattr(user, "coach_profile"):
                    logger.warning(
                        f"Coach profile not found for user {user.id} ({user.username})"
                    )
                    return Response(
                        {"error": "Coach profile not found"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                coach = user.coach_profile

            # Get teams where this coach is either head coach or assistant coach
            coach_teams = Team.objects.filter(
                Q(head_coach=coach) | Q(assistant_coach=coach)
            )

            logger.info(
                f"Coach {coach.user.username if coach.user else 'Unknown'} has {coach_teams.count()} teams assigned"
            )

            # If coach has no teams, return empty data instead of error
            if coach_teams.count() == 0:
                logger.warning(f"Coach {coach.user.username if coach.user else 'Unknown'} has no teams assigned")
                response_data = {
                    "team_overview": {
                        "total_teams": 0,
                        "total_players": 0,
                        "recent_training_sessions": 0,
                    },
                    "team_attendance": [],
                    "upcoming_games": [],
                    "recent_training_sessions": [],
                    "upcoming_training_sessions": [],
                    "recent_games": [],
                }
                serializer = CoachOverviewSerializer(response_data)
                return Response(serializer.data)

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
            now = timezone.now()
            today = now.date()
            # Convert timezone-aware time to naive time for comparison with database TimeField
            now_time = now.astimezone(timezone.get_current_timezone()).time()
            upcoming_games = Game.objects.filter(
                Q(home_team__in=coach_teams) | Q(away_team__in=coach_teams),
                status="scheduled",
            ).order_by("date", "time")

            upcoming_games_data = [
                {
                    "id": game.id,
                    "home_team": game.home_team.name,
                    "away_team": game.away_team.name,
                    "date": game.date,
                    "time": game.time,
                    "location": game.location,
                    "is_home": game.home_team in coach_teams,
                    "type": game.type,
                }
                for game in upcoming_games
            ]

            # Recent training sessions
            recent_sessions = TrainingSession.objects.filter(
                team__in=coach_teams, date__gte=last_30_days.date()
            ).order_by("-date")

            recent_sessions_data = [
                {
                    "id": session.id,
                    "title": session.title,
                    "date": session.date,
                    "location": session.location,
                    "team": session.team.name,
                    "attendance_count": session.player_records.filter(
                        attendance_status="present"
                    ).count(),
                    "total_players": session.player_records.count(),
                }
                for session in recent_sessions
            ]

            # Upcoming training sessions
            upcoming_sessions = TrainingSession.objects.filter(
                team__in=coach_teams, status="upcoming"
            ).order_by("date")

            upcoming_sessions_data = [
                {
                    "id": session.id,
                    "title": session.title,
                    "date": session.date,
                    "start_time": session.start_time,
                    "location": session.location,
                    "team": session.team.name,
                }
                for session in upcoming_sessions
            ]

            # Recent games for coach's teams
            recent_games = Game.objects.filter(
                Q(home_team__in=coach_teams) | Q(away_team__in=coach_teams),
                status="completed",
            ).order_by("-date")

            recent_games_data = [
                {
                    "id": game.id,
                    "home_team": game.home_team.name,
                    "away_team": game.away_team.name,
                    "date": game.date,
                    "time": game.time,
                    "location": game.location,
                    "home_team_score": game.home_team_score,
                    "away_team_score": game.away_team_score,
                    "is_home": game.home_team in coach_teams,
                    "result": (
                        "win"
                        if game.winner_team and game.winner_team in coach_teams
                        else (
                            "loss"
                            if game.winner_team and game.winner_team not in coach_teams
                            else "draw"
                        )
                    ),
                }
                for game in recent_games
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
                "upcoming_training_sessions": upcoming_sessions_data,
                "recent_games": recent_games_data,
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
        """Player progress analytics for coaches and admins

        Query parameters:
        - team_slug: Filter players by specific team (optional)
        - coach_id: View specific coach's data (admin only)
        """
        user = request.user
        team_slug = request.query_params.get("team_slug")
        coach_id = request.query_params.get("coach_id")

        try:
            # Import models at the beginning
            from teams.models import Coach, Team, Player
            from trainings.models import PlayerTraining, PlayerMetricRecord

            # For admin users, allow access to any team data or specific coach data
            if user.role == "Admin":
                if coach_id:
                    # Admin requesting specific coach data
                    try:
                        coach = Coach.objects.get(user_id=coach_id)
                        coach_teams = Team.objects.filter(
                            Q(head_coach=coach) | Q(assistant_coach=coach)
                        )
                    except Coach.DoesNotExist:
                        return Response({"error": "Coach not found"}, status=404)
                elif team_slug:
                    # Admin requesting specific team data
                    try:
                        specific_team = Team.objects.get(slug=team_slug)
                        coach_teams = Team.objects.filter(id=specific_team.id)
                    except Team.DoesNotExist:
                        return Response({"error": "Team not found"}, status=404)
                else:
                    # Admin requesting all teams (limit for performance)
                    coach_teams = Team.objects.all()[:10]  # Limit for performance
            else:
                # Coach users - check their assigned teams
                if not hasattr(user, "coach_profile"):
                    logger.warning(
                        f"Coach profile not found for user {user.id} ({user.username}) in player_progress"
                    )
                    return Response({"error": "Coach profile not found"}, status=400)

                # Get teams where this coach is either head coach or assistant coach
                coach_teams = Team.objects.filter(
                    Q(head_coach=user.coach_profile) | Q(assistant_coach=user.coach_profile)
                )

                # If team_slug is provided, filter to only that team (if coach has access)
                if team_slug:
                    coach_teams = coach_teams.filter(slug=team_slug)
                    if not coach_teams.exists():
                        return Response(
                            {"error": "You don't have access to this team"}, status=403
                        )

                logger.info(
                    f"Coach {user.username} has {coach_teams.count()} teams in player_progress"
                )

            # If no teams found, return empty data instead of error
            if coach_teams.count() == 0:
                logger.warning(
                    f"User {user.username} has no teams assigned in player_progress"
                )
                data = {"player_progress": []}
                serializer = CoachPlayerProgressSerializer(data)
                return Response(serializer.data)

            players = Player.objects.filter(team__in=coach_teams).select_related(
                "team", "user"
            )  # Optimize query
            # Get player progress data
            player_progress_data = []
            last_30_days = timezone.now() - timedelta(days=30)

            for player in players[:15]:  # Limit to top 15 for dashboard
                # Get recent training records
                recent_training_records = PlayerTraining.objects.filter(
                    player=player, session__date__gte=last_30_days.date()
                )

                # Get recent metric records
                recent_metrics = PlayerMetricRecord.objects.filter(
                    player_training__player=player,
                    recorded_at__gte=last_30_days,
                    value__isnull=False,  # Only include records with actual values
                ).order_by("-recorded_at")

                # Calculate attendance rate
                total_sessions = recent_training_records.count()
                attended_sessions = recent_training_records.filter(
                    attendance_status="present"
                ).count()

                attendance_rate = (
                    (attended_sessions / total_sessions * 100) if total_sessions > 0 else 0
                )

                # Calculate performance improvements
                overall_improvement = self._calculate_overall_improvement(player)
                recent_improvement = self._calculate_recent_improvement(
                    player, last_30_days
                )

                player_progress_data.append(
                    {
                        "player_id": player.user_id,
                        "player_name": player.user.get_full_name(),
                        "team": player.team.name if player.team else "No Team",
                        "team_slug": player.team.slug if player.team else None,
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

        except Exception as e:
            logger.error(f"Error in coach_player_progress: {str(e)}")
            return Response(
                {"error": "An error occurred while fetching coach player progress data"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _calculate_overall_improvement(self, player):
        """Calculate overall improvement across all metrics for a player"""
        from trainings.services.progress_service import ProgressService

        return ProgressService.calculate_overall_improvement(player)

    def _calculate_recent_improvement(self, player, last_30_days):
        """Calculate recent improvement for a player in the last 30 days"""
        try:
            from trainings.services.progress_service import ProgressService

            # Convert last_30_days datetime to date if needed
            start_date = (
                last_30_days.date() if hasattr(last_30_days, "date") else last_30_days
            )

            return ProgressService.calculate_recent_improvement(
                player, date_from=start_date
            )
        except Exception as e:
            logger.warning(
                f"Error calculating recent improvement for player {player.id}: {e}"
            )
            # Return a safe default value
            return {"percentage": 0.0, "metric_count": 0, "is_positive": False}

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def player_overview(self, request):
        """Personal dashboard for players - also supports admin/coach access to specific player data"""
        user = request.user
        player_id = request.query_params.get("player_id")

        try:
            # Import Player model at the beginning
            from teams.models import Player

            # If player_id is provided, check if user has permission to view other players
            if player_id:
                # Admin users can view any player
                if user.role == "Admin":
                    try:
                        player = Player.objects.get(user_id=player_id)
                    except Player.DoesNotExist:
                        return Response(
                            {"error": "Player not found"},
                            status=status.HTTP_404_NOT_FOUND,
                        )
                # Coach users can only view players from their teams
                elif user.role == "Coach" and hasattr(user, "coach_profile"):
                    try:
                        # Get teams where this coach is either head coach or assistant coach
                        coach_teams = Team.objects.filter(
                            Q(head_coach=user.coach_profile)
                            | Q(assistant_coach=user.coach_profile)
                        )
                        player = Player.objects.get(
                            user_id=player_id, team__in=coach_teams
                        )
                    except Player.DoesNotExist:
                        return Response(
                            {"error": "Player not found or not in your teams"},
                            status=status.HTTP_403_FORBIDDEN,
                        )
                else:
                    return Response(
                        {"error": "Permission denied"},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            else:
                # Default behavior - get current user's player profile
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
                    team=player.team, 
                    status="upcoming",
                    date__gte=timezone.now().date()
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
                # Use date and time fields for filtering upcoming games
                now = timezone.now()
                today = now.date()
                # Convert timezone-aware time to naive time for comparison with database TimeField
                now_time = now.astimezone(timezone.get_current_timezone()).time()
                upcoming_games = (
                    Game.objects.filter(
                        Q(home_team=player.team) | Q(away_team=player.team),
                        status="scheduled",
                    )
                    .exclude(date__isnull=True)
                    .exclude(time__isnull=True)
                    .filter(Q(date__gt=today) | (Q(date=today) & Q(time__gte=now_time)))
                    .order_by("date", "time")[:6]
                )

            upcoming_games_data = [
                {
                    "id": game.id,
                    "home_team": game.home_team.name,
                    "away_team": game.away_team.name,
                    "date": game.date,
                    "time": game.time,
                    "location": game.location,
                    "is_home": game.home_team == player.team,
                    "type": game.type,
                }
                for game in upcoming_games
            ]  # Recent performance metrics
            recent_metrics = PlayerMetricRecord.objects.filter(
                player_training__player=player,
                value__isnull=False,  # Only include records with actual values
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
                if record.value is not None  # Additional safety check
            ]  # Team information
            team_info = None
            if player.team:
                # Get coach names (both head and assistant)
                coaches = []
                if player.team.head_coach:
                    coaches.append(
                        f"Head: {player.team.head_coach.user.get_full_name()}"
                    )
                if player.team.assistant_coach:
                    coaches.append(
                        f"Assistant: {player.team.assistant_coach.user.get_full_name()}"
                    )

                coach_info = "; ".join(coaches) if coaches else "No Coaches"

                team_info = {
                    "name": player.team.name,
                    "sport": player.team.sport.name,
                    "total_players": player.team.players.count(),
                    "coach": coach_info,
                }
            # Player positions
            positions = list(
                player.position.values_list("name", flat=True)
            )  # Player info structure expected by frontend
            player_info = {
                "name": user.get_full_name(),
                "team": (
                    {
                        "name": player.team.name if player.team else None,
                        "sport": player.team.sport.name if player.team else None,
                    }
                    if player.team
                    else None
                ),
                "position": ", ".join(positions) if positions else None,
                "jersey_number": player.jersey_number,
                "height": float(player.height) if player.height else None,
                "weight": float(player.weight) if player.weight else None,
            }

            # Training summary structure expected by frontend
            training_summary = {
                "total_sessions": attended_sessions,
                "attendance_rate": round(attendance_rate, 2),
                "last_training_date": (
                    player_training_records.filter(attendance_status="present")
                    .order_by("-session__date")
                    .first()
                    .session.date.strftime("%Y-%m-%d")
                    if player_training_records.filter(
                        attendance_status="present"
                    ).exists()
                    else None
                ),
            }

            # Transform recent_metrics to recent_stats format
            recent_stats = {}
            if recent_metrics_data:
                # Group metrics by name and get the latest value for each
                metrics_by_name = {}
                for metric in recent_metrics_data:
                    metric_name = metric["metric_name"].lower().replace(" ", "_")
                    if metric_name not in metrics_by_name:
                        metrics_by_name[metric_name] = metric["value"]
                recent_stats = metrics_by_name

            response_data = {
                "player_info": player_info,
                "training_summary": training_summary,
                "upcoming_games": upcoming_games_data,
                "recent_stats": recent_stats,
                "team_info": team_info,
                # Keep existing data for backward compatibility
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
                "recent_metrics": recent_metrics_data,
            }

            serializer = PlayerOverviewSerializer(response_data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error in player_overview: {str(e)}")
            return Response(
                {"error": "An error occurred while fetching player overview data"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def player_progress(self, request):
        """Personal progress tracking for players - also supports admin/coach access to specific player data"""
        user = request.user
        player_id = request.query_params.get("player_id")

        try:
            # Import Player model at the beginning
            from teams.models import Player

            # If player_id is provided, check if user has permission to view other players
            if player_id:
                # Admin users can view any player
                if user.role == "Admin":
                    try:
                        player = Player.objects.get(user_id=player_id)
                    except Player.DoesNotExist:
                        return Response(
                            {"error": "Player not found"},
                            status=status.HTTP_404_NOT_FOUND,
                        )
                # Coach users can only view players from their teams
                elif user.role == "Coach" and hasattr(user, "coach_profile"):
                    try:
                        # Get teams where this coach is either head coach or assistant coach
                        coach_teams = Team.objects.filter(
                            Q(head_coach=user.coach_profile)
                            | Q(assistant_coach=user.coach_profile)
                        )
                        player = Player.objects.get(
                            user_id=player_id, team__in=coach_teams
                        )
                    except Player.DoesNotExist:
                        return Response(
                            {"error": "Player not found or not in your teams"},
                            status=status.HTTP_403_FORBIDDEN,
                        )
                else:
                    return Response(
                        {"error": "Permission denied"},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            else:
                # Default behavior - get current user's player profile
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
                    player_training__player=player,
                    recorded_at__gte=start_date,
                    value__isnull=False,  # Only include records with actual values
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

            # Get metric trends (last 3 months) with proper improvement calculations
            from trainings.services.progress_service import ProgressService
            from trainings.utils import calculate_normalized_improvement

            # Calculate 3-months date range for consistent timeframe
            three_months_ago = timezone.now() - timedelta(days=90)
            metric_trends = {}
            progress_metrics = []

            unique_metrics = (
                PlayerMetricRecord.objects.filter(
                    player_training__player=player,
                    recorded_at__gte=three_months_ago,
                    value__isnull=False,  # Only include records with actual values
                )
                .values_list("metric__name", flat=True)
                .distinct()
            )

            for metric_name in unique_metrics:
                recent_records = PlayerMetricRecord.objects.filter(
                    player_training__player=player,
                    metric__name=metric_name,
                    recorded_at__gte=three_months_ago,
                    value__isnull=False,  # Only include records with actual values
                ).order_by("recorded_at")

                if not recent_records.exists():
                    continue

                # Get only the latest and first records for improvement calculation
                first_record = recent_records.first()
                latest_record = recent_records.last()

                # Calculate accurate improvement percentage using normalized improvement function with weights
                improvement_percentage = 0
                if first_record and latest_record and first_record != latest_record:
                    first_value = float(first_record.value)
                    last_value = float(latest_record.value)

                    # Get the metric object to check if lower is better and get normalization weight
                    metric_obj = first_record.metric
                    if metric_obj:
                        # Get the normalization weight from the metric unit
                        normalization_weight = (
                            float(metric_obj.metric_unit.normalization_weight)
                            if metric_obj.metric_unit
                            and metric_obj.metric_unit.normalization_weight
                            else 1.0
                        )

                        # Use the normalized improvement calculation function with weight
                        improvement_result = calculate_normalized_improvement(
                            last_value,
                            first_value,
                            metric_obj.is_lower_better,
                            normalization_weight,
                        )
                        improvement_percentage = improvement_result["percentage"]

                # Only store the latest metric value with improvement percentage
                metric_data = [
                    {
                        "value": float(latest_record.value),
                        "date": latest_record.player_training.session.date,
                        "unit": latest_record.metric.metric_unit.code,
                        "improvement_percentage": improvement_percentage,
                    }
                ]

                metric_trends[metric_name] = metric_data

                # Create progress metrics format expected by frontend
                if metric_data:
                    latest_value = metric_data[-1]["value"] if metric_data else 0
                    earliest_value = (
                        metric_data[0]["value"]
                        if len(metric_data) > 1
                        else latest_value
                    )
                    # Assume a target value (in real app, this would come from training goals)
                    target_value = latest_value * 1.2  # 20% improvement target
                    progress_percentage = (
                        min((latest_value / target_value) * 100, 100)
                        if target_value > 0
                        else 0
                    )

                    progress_metrics.append(
                        {
                            "metric_name": metric_name,
                            "current_value": latest_value,
                            "target_value": target_value,
                            "unit": metric_data[-1]["unit"],
                            "progress_percentage": progress_percentage,
                            "improvement_percentage": float(
                                improvement_percentage
                            ),  # Ensure it's a number
                        }
                    )  # Use ProgressService to calculate weighted overall improvement for consistent average
            overall_improvement = ProgressService.calculate_overall_improvement(
                player, three_months_ago, timezone.now()
            )

            # Calculate recent improvement for the last 90 days (consistent with dashboard data timeframe)
            recent_improvement = ProgressService.calculate_recent_improvement(
                player, three_months_ago, timezone.now()
            )

            # Calculate progress summary expected by frontend using weighted improvement calculations
            total_metrics = len(progress_metrics)
            # Calculate total training sessions within the 3-month date range
            total_training_sessions = PlayerTraining.objects.filter(
                player=player, session__date__gte=three_months_ago.date()
            ).count()

            # Use the weighted overall improvement if available, otherwise fall back to simple average
            if overall_improvement:
                average_improvement = overall_improvement["percentage"]
            else:
                average_improvement = (
                    sum(
                        metric.get("improvement_percentage", 0)
                        for metric in progress_metrics
                    )
                    / total_metrics
                    if total_metrics > 0
                    else 0
                )

            # Use recent improvement if available, otherwise fallback to average improvement
            if recent_improvement:
                recent_improvement_percentage = recent_improvement["percentage"]
            else:
                recent_improvement_percentage = average_improvement

            goals_achieved = sum(
                1
                for metric in progress_metrics
                if metric.get("progress_percentage", 0) >= 100
            )

            frontend_progress_summary = {
                "training_sessions": total_training_sessions,
                "average_improvement": average_improvement,
                "recent_improvement": recent_improvement_percentage,
                "goals_achieved": goals_achieved,
            }
            data = {
                # Frontend expected structure
                "progress_metrics": progress_metrics,
                "progress_summary": frontend_progress_summary,
                # Keep original structure for backward compatibility
                "progress_summary_detailed": progress_data,
                "metric_trends": metric_trends,
            }
            serializer = PlayerProgressDetailSerializer(data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error in player_progress: {str(e)}")
            return Response(
                {"error": "An error occurred while fetching player progress data"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAdminUser])
    def admin_insights(self, request):
        """Advanced insights and recommendations for administrators with AI analysis"""
        try:
            last_30_days = timezone.now() - timedelta(days=30)
            last_90_days = timezone.now() - timedelta(days=90)

            insights = []
            recommendations = []
            ai_insights = None

            # Check if AI analysis is requested
            use_ai = request.query_params.get("ai", "false").lower() == "true"
            # Generate AI-powered insights if requested
            if use_ai:
                try:
                    from .ai_analysis import analyze_system_health, collect_system_data

                    # Collect comprehensive system data
                    system_data = collect_system_data()

                    # Generate AI analysis
                    ai_insights = analyze_system_health(system_data)

                    # Convert AI insights to standard insight format
                    if "ai_analysis" in ai_insights:
                        ai_analysis = ai_insights["ai_analysis"]

                        # Add AI-generated insights to the insights list
                        if "Critical Issues" in ai_analysis:
                            insights.append(
                                {
                                    "type": "warning",
                                    "title": "AI Analysis: Critical Issues",
                                    "message": ai_analysis["Critical Issues"],
                                    "action": "Review AI recommendations for immediate actions",
                                    "source": "ai",
                                }
                            )

                        if "Success Indicators" in ai_analysis:
                            insights.append(
                                {
                                    "type": "success",
                                    "title": "AI Analysis: Success Indicators",
                                    "message": ai_analysis["Success Indicators"],
                                    "action": "Continue current successful strategies",
                                    "source": "ai",
                                }
                            )

                        if "Opportunity Areas" in ai_analysis:
                            insights.append(
                                {
                                    "type": "info",
                                    "title": "AI Analysis: Growth Opportunities",
                                    "message": ai_analysis["Opportunity Areas"],
                                    "action": "Explore identified improvement areas",
                                    "source": "ai",
                                }
                            )

                        # Add AI recommendations
                        if "Strategic Recommendations" in ai_analysis:
                            recommendations.append(
                                {
                                    "priority": "high",
                                    "category": "ai_strategic",
                                    "title": "AI Strategic Recommendations",
                                    "description": ai_analysis[
                                        "Strategic Recommendations"
                                    ],
                                    "suggested_actions": (
                                        ai_analysis.get("Priority Actions", "").split(
                                            ". "
                                        )
                                        if "Priority Actions" in ai_analysis
                                        else [
                                            "Review AI analysis for specific actions",
                                            "Implement suggested improvements",
                                            "Monitor system health metrics",
                                        ]
                                    ),
                                    "source": "ai",
                                }
                            )

                        # When AI is enabled, return only AI insights
                        data = {
                            "insights": insights,
                            "recommendations": recommendations,
                            "system_health_score": self._calculate_system_health_score(),
                            "generated_at": timezone.now().isoformat(),
                            "ai_analysis_enabled": use_ai,
                            "ai_insights": ai_insights,
                            "summary": {
                                "total_insights": len(insights),
                                "warnings": len(
                                    [i for i in insights if i["type"] == "warning"]
                                ),
                                "opportunities": len(
                                    [i for i in insights if i["type"] == "info"]
                                ),
                                "successes": len(
                                    [i for i in insights if i["type"] == "success"]
                                ),
                                "ai_insights": len(
                                    [i for i in insights if i.get("source") == "ai"]
                                ),
                            },
                        }
                        return Response(data)

                except Exception as ai_error:
                    # If AI analysis fails, add a notification
                    insights.append(
                        {
                            "type": "warning",
                            "title": "AI Analysis Error",
                            "message": f"AI-powered insights unavailable: {str(ai_error)}",
                            "action": "Please try again or use standard analysis",
                        }
                    )

                    # Return error response for AI mode
                    data = {
                        "insights": insights,
                        "recommendations": [],
                        "system_health_score": self._calculate_system_health_score(),
                        "generated_at": timezone.now().isoformat(),
                        "ai_analysis_enabled": use_ai,
                        "ai_insights": None,
                        "summary": {
                            "total_insights": len(insights),
                            "warnings": 1,
                            "opportunities": 0,
                            "successes": 0,
                            "ai_insights": 0,
                        },
                    }
                    return Response(data)
            # When AI is disabled, use built-in rule-based analysis
            # Check for teams that need attention
            teams_without_recent_activity = Team.objects.exclude(
                Q(training_sessions__date__gte=last_30_days.date())
                | Q(home_games__date__gte=last_30_days.date())
                | Q(away_games__date__gte=last_30_days.date())
            ).count()

            if teams_without_recent_activity > 0:
                insights.append(
                    {
                        "type": "warning",
                        "title": "Inactive Teams Detected",
                        "message": f"{teams_without_recent_activity} teams have had no activity in the last 30 days",
                        "action": "Review team status and contact coaches",
                    }
                )  # Check for coaches with low engagement
            low_engagement_coaches = (
                Coach.objects.annotate(
                    recent_sessions=Count(
                        "head_coached_teams__training_sessions",
                        filter=Q(
                            head_coached_teams__training_sessions__date__gte=last_30_days.date()
                        ),
                    )
                    + Count(
                        "assistant_coached_teams__training_sessions",
                        filter=Q(
                            assistant_coached_teams__training_sessions__date__gte=last_30_days.date()
                        ),
                    )
                )
                .filter(
                    Q(head_coached_teams__isnull=False)
                    | Q(assistant_coached_teams__isnull=False),
                    recent_sessions__lt=2,
                )
                .count()
            )

            if low_engagement_coaches > 0:
                insights.append(
                    {
                        "type": "info",
                        "title": "Coach Engagement Opportunity",
                        "message": f"{low_engagement_coaches} coaches have conducted fewer than 2 training sessions this month",
                        "action": "Provide coaching support or training resources",
                    }
                )

            # Check attendance trends
            recent_attendance_records = PlayerTraining.objects.filter(
                session__date__gte=last_30_days.date()
            )
            if recent_attendance_records.exists():
                total_records = recent_attendance_records.count()
                present_records = recent_attendance_records.filter(
                    attendance_status="present"
                ).count()
                attendance_rate = (present_records / total_records) * 100

                if attendance_rate < 70:
                    insights.append(
                        {
                            "type": "warning",
                            "title": "Low Attendance Alert",
                            "message": f"Overall attendance rate is {attendance_rate:.1f}% (below 70% threshold)",
                            "action": "Investigate attendance issues and consider engagement strategies",
                        }
                    )
                elif attendance_rate > 85:
                    insights.append(
                        {
                            "type": "success",
                            "title": "Excellent Attendance",
                            "message": f"Outstanding attendance rate of {attendance_rate:.1f}%",
                            "action": "Continue current engagement strategies",
                        }
                    )

            # Check for unassigned players
            unassigned_players = Player.objects.filter(team__isnull=True).count()
            if unassigned_players > 0:
                insights.append(
                    {
                        "type": "info",
                        "title": "Players Need Team Assignment",
                        "message": f"{unassigned_players} players are not assigned to any team",
                        "action": "Review player assignments and create teams if needed",
                    }
                )

            # Check for teams with insufficient players
            understaffed_teams = (
                Team.objects.annotate(player_count=Count("players"))
                .filter(player_count__lt=F('sport__max_players_on_field'))
                .count()
            )

            if understaffed_teams > 0:
                insights.append(
                    {
                        "type": "warning",
                        "title": "Teams Need More Players",
                        "message": f"{understaffed_teams} teams have fewer than the minimum players required for their sport",
                        "action": "Recruit more players or consider team consolidation",
                    }
                )

            # Check for teams without coaches
            teams_without_coaches = Team.objects.filter(
                head_coach__isnull=True, assistant_coach__isnull=True
            ).count()

            if teams_without_coaches > 0:
                insights.append(
                    {
                        "type": "warning",
                        "title": "Teams Need Coach Assignment",
                        "message": f"{teams_without_coaches} teams have no head coach or assistant coach assigned",
                        "action": "Assign coaches to teams or recruit new coaching staff",
                    }
                )

            # Generate recommendations based on system analysis
            if Team.objects.count() > 0:
                avg_players_per_team = (
                    Player.objects.filter(team__isnull=False).count()
                    / Team.objects.count()
                )
                if avg_players_per_team < 8:
                    recommendations.append(
                        {
                            "priority": "high",
                            "category": "recruitment",
                            "title": "Increase Player Recruitment",
                            "description": f"Average of {avg_players_per_team:.1f} players per team is below optimal range (8-15)",
                            "suggested_actions": [
                                "Launch recruitment campaigns",
                                "Partner with schools for player development",
                                "Organize open trials and events",
                            ],
                        }
                    )

            # System health score calculation
            health_score = self._calculate_system_health_score()

            # Additional recommendations based on health score
            if health_score < 60:
                recommendations.append(
                    {
                        "priority": "high",
                        "category": "system_health",
                        "title": "System Health Improvement Needed",
                        "description": f"System health score is {health_score}/100, indicating areas for improvement",
                        "suggested_actions": [
                            "Address inactive teams and coaches",
                            "Improve player assignment processes",
                            "Increase training session frequency",
                        ],
                    }
                )

            # Return built-in insights when AI is disabled
            data = {
                "insights": insights[:10],  # Limit to top 10 insights
                "recommendations": recommendations[
                    :5
                ],  # Limit to top 5 recommendations
                "system_health_score": health_score,
                "generated_at": timezone.now().isoformat(),
                "ai_analysis_enabled": use_ai,
                "ai_insights": None,  # No AI analysis when disabled
                "summary": {
                    "total_insights": len(insights),
                    "warnings": len([i for i in insights if i["type"] == "warning"]),
                    "opportunities": len([i for i in insights if i["type"] == "info"]),
                    "successes": len([i for i in insights if i["type"] == "success"]),
                    "ai_insights": 0,  # No AI insights when disabled
                },
            }

            return Response(data)

        except Exception as e:
            logger.error(f"Error in admin_insights: {str(e)}")
            return Response(
                {"error": "An error occurred while generating insights"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAdminUser])
    def admin_reports(self, request):
        """Generate comprehensive reports for administrators"""
        try:
            report_type = request.query_params.get("type", "summary")
            date_from = request.query_params.get("date_from")
            date_to = request.query_params.get("date_to")

            # Set default date range if not provided
            if not date_from:
                date_from = (timezone.now() - timedelta(days=30)).date()
            else:
                date_from = timezone.datetime.strptime(date_from, "%Y-%m-%d").date()

            if not date_to:
                date_to = timezone.now().date()
            else:
                date_to = timezone.datetime.strptime(date_to, "%Y-%m-%d").date()

            if report_type == "attendance":
                return self._generate_attendance_report(date_from, date_to)
            elif report_type == "performance":
                return self._generate_performance_report(date_from, date_to)
            elif report_type == "usage":
                return self._generate_usage_report(date_from, date_to)
            else:
                return self._generate_summary_report(date_from, date_to)

        except Exception as e:
            logger.error(f"Error in admin_reports: {str(e)}")
            return Response(
                {"error": "An error occurred while generating reports"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _calculate_system_health_score(self):
        """Calculate an overall system health score (0-100)"""
        try:
            score = 100

            # Deduct points for system issues
            total_teams = Team.objects.count()
            if total_teams > 0:  # Teams without coaches
                teams_without_coaches = Team.objects.filter(
                    head_coach__isnull=True, assistant_coach__isnull=True
                ).count()
                score -= (teams_without_coaches / total_teams) * 20

                # Teams with too few players
                understaffed_teams = (
                    Team.objects.annotate(player_count=Count("players"))
                    .filter(player_count__lt=F('sport__max_players_on_field'))
                    .count()
                )
                score -= (understaffed_teams / total_teams) * 15

                # Inactive teams (last 30 days)
                last_30_days = timezone.now() - timedelta(days=30)
                inactive_teams = Team.objects.exclude(
                    Q(training_sessions__date__gte=last_30_days.date())
                    | Q(home_games__date__gte=last_30_days.date())
                    | Q(away_games__date__gte=last_30_days.date())
                ).count()
                score -= (inactive_teams / total_teams) * 25

            # Check overall attendance rate
            recent_attendance = PlayerTraining.objects.filter(
                session__date__gte=(timezone.now() - timedelta(days=30)).date()
            )
            if recent_attendance.exists():
                present_count = recent_attendance.filter(
                    attendance_status="present"
                ).count()
                attendance_rate = (present_count / recent_attendance.count()) * 100
                if attendance_rate < 80:
                    score -= (80 - attendance_rate) * 0.5

            # Check for unassigned players
            total_players = Player.objects.count()
            if total_players > 0:
                unassigned_players = Player.objects.filter(team__isnull=True).count()
                score -= (unassigned_players / total_players) * 10

            return max(0, min(100, round(score)))

        except Exception as e:
            logger.error(f"Error calculating system health score: {str(e)}")
            return 50  # Default middle score if calculation fails

    def _generate_attendance_report(self, date_from, date_to):
        """Generate detailed attendance report"""
        # Get all training sessions in the date range
        training_sessions = TrainingSession.objects.filter(
            date__gte=date_from, date__lte=date_to
        ).select_related("team", "team__sport")

        team_attendance = {}
        overall_stats = {
            "total_sessions": training_sessions.count(),
            "total_records": 0,
            "total_present": 0,
            "total_absent": 0,
        }

        for session in training_sessions:
            team_name = session.team.name
            if team_name not in team_attendance:
                team_attendance[team_name] = {
                    "team_id": session.team.id,
                    "sport": (
                        session.team.sport.name if session.team.sport else "No Sport"
                    ),
                    "sessions": 0,
                    "total_records": 0,
                    "present": 0,
                    "absent": 0,
                    "attendance_rate": 0,
                }

            team_attendance[team_name]["sessions"] += 1

            # Get attendance records for this session
            records = PlayerTraining.objects.filter(session=session)
            present_count = records.filter(attendance_status="present").count()
            absent_count = records.filter(attendance_status="absent").count()

            team_attendance[team_name]["total_records"] += records.count()
            team_attendance[team_name]["present"] += present_count
            team_attendance[team_name]["absent"] += absent_count

            overall_stats["total_records"] += records.count()
            overall_stats["total_present"] += present_count
            overall_stats["total_absent"] += absent_count

        # Calculate attendance rates
        for team_data in team_attendance.values():
            if team_data["total_records"] > 0:
                team_data["attendance_rate"] = round(
                    (team_data["present"] / team_data["total_records"]) * 100, 2
                )

        overall_attendance_rate = 0
        if overall_stats["total_records"] > 0:
            overall_attendance_rate = round(
                (overall_stats["total_present"] / overall_stats["total_records"]) * 100,
                2,
            )

        attendance_data = {
            "report_type": "attendance",
            "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "overall_stats": {
                **overall_stats,
                "attendance_rate": overall_attendance_rate,
            },
            "team_breakdown": list(team_attendance.values()),
            "generated_at": timezone.now().isoformat(),
        }

        return Response(attendance_data)

    def _generate_performance_report(self, date_from, date_to):
        """Generate team performance report"""
        teams = Team.objects.all().select_related("sport")
        team_performance = []

        for team in teams:
            # Get games in date range
            games = Game.objects.filter(
                Q(home_team=team) | Q(away_team=team),
                date__gte=date_from,
                date__lte=date_to,
                status="completed",
            )

            wins = 0
            losses = 0
            total_score_for = 0
            total_score_against = 0

            for game in games:
                if game.home_team == team:
                    team_score = game.home_team_score or 0
                    opponent_score = game.away_team_score or 0
                else:
                    team_score = game.away_team_score or 0
                    opponent_score = game.home_team_score or 0

                total_score_for += team_score
                total_score_against += opponent_score

                if team_score > opponent_score:
                    wins += 1
                elif team_score < opponent_score:
                    losses += 1

            games_played = wins + losses
            win_rate = (wins / games_played * 100) if games_played > 0 else 0
            avg_score_for = total_score_for / games_played if games_played > 0 else 0
            avg_score_against = (
                total_score_against / games_played if games_played > 0 else 0
            )

            team_performance.append(
                {
                    "team_id": team.id,
                    "team_name": team.name,
                    "sport": team.sport.name if team.sport else "No Sport",
                    "games_played": games_played,
                    "wins": wins,
                    "losses": losses,
                    "win_rate": round(win_rate, 2),
                    "avg_score_for": round(avg_score_for, 2),
                    "avg_score_against": round(avg_score_against, 2),
                    "score_differential": round(avg_score_for - avg_score_against, 2),
                }
            )

        # Sort by win rate and games played
        team_performance.sort(
            key=lambda x: (x["win_rate"], x["games_played"]), reverse=True
        )

        performance_data = {
            "report_type": "performance",
            "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "team_performance": team_performance,
            "summary": {
                "teams_with_games": len(
                    [t for t in team_performance if t["games_played"] > 0]
                ),
                "total_games": sum(t["games_played"] for t in team_performance),
                "avg_win_rate": (
                    round(
                        sum(
                            t["win_rate"]
                            for t in team_performance
                            if t["games_played"] > 0
                        )
                        / len([t for t in team_performance if t["games_played"] > 0]),
                        2,
                    )
                    if any(t["games_played"] > 0 for t in team_performance)
                    else 0
                ),
            },
            "generated_at": timezone.now().isoformat(),
        }

        return Response(performance_data)

    def _generate_usage_report(self, date_from, date_to):
        """Generate system usage report"""
        # User activity - users who were active within the date range
        active_users = User.objects.filter(
            last_login__gte=timezone.make_aware(
                timezone.datetime.combine(date_from, timezone.datetime.min.time())
            ),
            last_login__lte=timezone.make_aware(
                timezone.datetime.combine(date_to, timezone.datetime.max.time())
            )
        ).count()

        new_users = User.objects.filter(
            date_joined__gte=timezone.make_aware(
                timezone.datetime.combine(date_from, timezone.datetime.min.time())
            ),
            date_joined__lte=timezone.make_aware(
                timezone.datetime.combine(date_to, timezone.datetime.max.time())
            ),
        ).count()

        # Activity metrics
        training_sessions = TrainingSession.objects.filter(
            date__gte=date_from, date__lte=date_to
        ).count()

        games_played = Game.objects.filter(
            date__gte=date_from, date__lte=date_to, status="completed"
        ).count()

        games_scheduled = Game.objects.filter(
            date__gte=date_from, date__lte=date_to, status="scheduled"
        ).count()

        # Feature utilization
        teams_with_activity = (
            Team.objects.filter(
                Q(training_sessions__date__gte=date_from)
                | Q(home_games__date__gte=date_from)
                | Q(away_games__date__gte=date_from)
            )
            .distinct()
            .count()
        )

        total_teams = Team.objects.count()
        utilization_rate = (
            (teams_with_activity / total_teams * 100) if total_teams > 0 else 0
        )

        usage_data = {
            "report_type": "usage",
            "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "user_activity": {
                "active_users": active_users,
                "new_users": new_users,
                "total_users": User.objects.count(),
            },
            "system_activity": {
                "training_sessions": training_sessions,
                "games_completed": games_played,
                "games_scheduled": games_scheduled,
                "teams_with_activity": teams_with_activity,
                "team_utilization_rate": round(utilization_rate, 2),
            },
            "generated_at": timezone.now().isoformat(),
        }

        return Response(usage_data)

    def _generate_summary_report(self, date_from, date_to):
        """Generate comprehensive summary report"""
        summary_data = {
            "report_type": "summary",
            "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "key_metrics": {
                "total_teams": Team.objects.count(),
                "total_players": Player.objects.filter(team__isnull=False).count(),
                "total_coaches": Coach.objects.count(),
                "active_leagues": League.objects.filter(
                    seasons__status__in=["ongoing", "upcoming"]
                )
                .distinct()
                .count(),
                "games_in_period": Game.objects.filter(
                    date__gte=date_from, date__lte=date_to
                ).count(),
                "training_sessions_in_period": TrainingSession.objects.filter(
                    date__gte=date_from, date__lte=date_to
                ).count(),
            },
            "health_indicators": {
                "system_health_score": self._calculate_system_health_score(),
                "unassigned_players": Player.objects.filter(team__isnull=True).count(),
                "teams_without_coaches": Team.objects.filter(
                    head_coach__isnull=True, assistant_coach__isnull=True
                ).count(),
                "inactive_teams": Team.objects.exclude(
                    Q(training_sessions__date__gte=date_from)
                    | Q(home_games__date__gte=date_from)
                    | Q(away_games__date__gte=date_from)
                ).count(),
            },
            "generated_at": timezone.now().isoformat(),
        }

        return Response(summary_data)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def dashboard_summary(self, request):
        """
        Get comprehensive dashboard summary data using DashboardSummaryService.
        Suitable for main dashboard overview across all user roles.
        """
        try:
            days = int(request.query_params.get("days", 30))

            # Get data from DashboardSummaryService
            system_overview = DashboardSummaryService.get_system_overview(days)
            health_indicators = DashboardSummaryService.get_health_indicators()
            user_activity_summary = DashboardSummaryService.get_user_activity_summary(
                days
            )
            performance_indicators = DashboardSummaryService.get_performance_indicators(
                days
            )
            trend_data = DashboardSummaryService.get_trend_data(days)
            distribution_stats = DashboardSummaryService.get_distribution_stats(days)

            # Combine all data
            summary_data = {
                "system_overview": system_overview,
                "health_indicators": health_indicators,
                "user_activity_summary": user_activity_summary,
                "performance_indicators": performance_indicators,
                "trend_data": trend_data,
                "distribution_stats": distribution_stats,
            }

            serializer = DashboardSummarySerializer(summary_data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error in dashboard_summary: {str(e)}")
            return Response(
                {"error": "Failed to fetch dashboard summary"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def training_summary(self, request):
        """
        Get training summary data for dashboard visualization.
        """
        try:
            days = int(request.query_params.get("days", 30))

            # Get data from TrainingSummaryService
            training_overview = TrainingSummaryService.get_training_overview(days)
            training_trends = TrainingSummaryService.get_training_trends(days)
            training_performance = TrainingSummaryService.get_training_performance(days)
            health_indicators = TrainingSummaryService.get_training_health_indicators()

            # Combine all data
            summary_data = {
                "training_overview": training_overview,
                "training_trends": training_trends,
                "training_performance": training_performance,
                "health_indicators": health_indicators,
            }

            serializer = TrainingSummarySerializer(summary_data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error in training_summary: {str(e)}")
            return Response(
                {"error": "Failed to fetch training summary"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def league_summary(self, request):
        """
        Get league summary data for dashboard visualization.
        """
        try:
            days = int(request.query_params.get("days", 30))

            # Get data from LeagueSummaryService
            league_overview = LeagueSummaryService.get_league_overview(days)
            league_trends = LeagueSummaryService.get_league_trends(days)
            league_performance = LeagueSummaryService.get_league_performance(days)
            health_indicators = LeagueSummaryService.get_league_health_indicators()

            # Combine all data
            summary_data = {
                "league_overview": league_overview,
                "league_trends": league_trends,
                "league_performance": league_performance,
                "health_indicators": health_indicators,
            }

            serializer = LeagueSummarySerializer(summary_data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error in league_summary: {str(e)}")
            return Response(
                {"error": "Failed to fetch league summary"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def game_summary(self, request):
        """
        Get game summary data for dashboard visualization.
        """
        try:
            days = int(request.query_params.get("days", 30))

            # Get data from GameSummaryService
            game_overview = GameSummaryService.get_game_overview(days)
            game_trends = GameSummaryService.get_game_trends(days)
            game_performance = GameSummaryService.get_game_performance(days)
            health_indicators = GameSummaryService.get_game_health_indicators()

            # Combine all data
            summary_data = {
                "game_overview": game_overview,
                "game_trends": game_trends,
                "game_performance": game_performance,
                "health_indicators": health_indicators,
            }

            serializer = GameSummarySerializer(summary_data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error in game_summary: {str(e)}")
            return Response(
                {"error": "Failed to fetch game summary"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def analytics(self, request):
        """
        Get comprehensive analytics data including engagement and performance comparisons.
        """
        try:
            days = int(request.query_params.get("days", 30))

            # Get data from AnalyticsService
            engagement_analytics = AnalyticsService.get_engagement_analytics(days)
            performance_comparison = AnalyticsService.get_performance_comparison(days)

            # Combine all data
            analytics_data = {
                "engagement_analytics": engagement_analytics,
                "performance_comparison": performance_comparison,
            }

            serializer = AnalyticsSerializer(analytics_data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error in analytics: {str(e)}")
            return Response(
                {"error": "Failed to fetch analytics data"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def chart_data(self, request):
        """
        Get formatted chart data for specific chart types.

        Query parameters:
        - chart_type: 'activity_timeline', 'sport_distribution', 'performance_comparison', 'engagement_heatmap'
        - days: Number of days to analyze (default: 30)
        """
        try:
            chart_type = request.query_params.get("chart_type", "activity_timeline")
            days = int(request.query_params.get("days", 30))

            # Get chart data from AnalyticsService
            chart_data = AnalyticsService.get_chart_data(chart_type, days)

            serializer = ChartDataSerializer(chart_data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error in chart_data: {str(e)}")
            return Response(
                {"error": "Failed to fetch chart data"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # New Summary Service Endpoints
    @action(detail=False, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def training_summary(self, request):
        """
        Get comprehensive training summary data for dashboard.

        Query parameters:
        - days: Number of days to analyze (default: 30)
        - weeks: Number of weeks for trends (default: 8)
        """
        try:
            days = int(request.query_params.get("days", 30))
            weeks = int(request.query_params.get("weeks", 8))

            summary_data = {
                "overview": TrainingSummaryService.get_training_overview(days),
                "weekly_trends": TrainingSummaryService.get_weekly_trends(weeks),
                "performance_indicators": TrainingSummaryService.get_performance_indicators(),
                "recent_activity": TrainingSummaryService.get_recent_activity(),
                "health_indicators": TrainingSummaryService.get_training_health_indicators(),
            }

            return Response(summary_data)

        except Exception as e:
            logger.error(f"Error in training_summary: {str(e)}")
            return Response(
                {"error": "Failed to fetch training summary"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def game_summary(self, request):
        """
        Get comprehensive game summary data for dashboard.

        Query parameters:
        - days: Number of days to analyze (default: 30)
        - weeks: Number of weeks for trends (default: 8)
        - limit: Number of recent activities (default: 10)
        """
        try:
            days = int(request.query_params.get("days", 30))
            weeks = int(request.query_params.get("weeks", 8))
            limit = int(request.query_params.get("limit", 10))

            summary_data = {
                "overview": GameSummaryService.get_game_overview(days),
                "weekly_trends": GameSummaryService.get_weekly_trends(weeks),
                "performance_indicators": GameSummaryService.get_performance_indicators(),
                "statistics_summary": GameSummaryService.get_game_statistics_summary(),
                "recent_activity": GameSummaryService.get_recent_activity(limit),
                "health_indicators": GameSummaryService.get_game_health_indicators(),
            }

            return Response(summary_data)

        except Exception as e:
            logger.error(f"Error in game_summary: {str(e)}")
            return Response(
                {"error": "Failed to fetch game summary"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def league_summary(self, request):
        """
        Get comprehensive league summary data for dashboard.

        Query parameters:
        - days: Number of days to analyze (default: 30)
        - limit: Number of recent activities (default: 10)
        """
        try:
            days = int(request.query_params.get("days", 30))
            limit = int(request.query_params.get("limit", 10))

            summary_data = {
                "overview": LeagueSummaryService.get_league_overview(days),
                "performance_indicators": LeagueSummaryService.get_performance_indicators(),
                "recent_activity": LeagueSummaryService.get_recent_activity(limit),
                "health_indicators": LeagueSummaryService.get_league_health_indicators(),
            }

            return Response(summary_data)

        except Exception as e:
            logger.error(f"Error in league_summary: {str(e)}")
            return Response(
                {"error": "Failed to fetch league summary"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAdminUser])
    def analytics_summary(self, request):
        """
        Get comprehensive analytics data for dashboard.

        Query parameters:
        - days: Number of days for engagement analysis (default: 30)
        - months: Number of months for growth analysis (default: 12)
        - heatmap_days: Number of days for heatmap (default: 30)
        """
        try:
            days = int(request.query_params.get("days", 30))
            months = int(request.query_params.get("months", 12))
            heatmap_days = int(request.query_params.get("heatmap_days", 30))

            summary_data = {
                "engagement_analytics": AnalyticsService.get_engagement_analytics(days),
                "comparative_analytics": AnalyticsService.get_comparative_analytics(),
                "growth_analytics": AnalyticsService.get_growth_analytics(months),
                "activity_heatmap": AnalyticsService.get_activity_heatmap(heatmap_days),
                "performance_analytics": AnalyticsService.get_performance_analytics(),
            }

            return Response(summary_data)

        except Exception as e:
            logger.error(f"Error in analytics_summary: {str(e)}")
            return Response(
                {"error": "Failed to fetch analytics summary"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def system_summary(self, request):
        """
        Get overall system summary combining all modules.

        Query parameters:
        - days: Number of days to analyze (default: 7)
        """
        try:
            days = int(request.query_params.get("days", 7))

            summary_data = {
                "system_overview": DashboardSummaryService.get_system_overview(),
                "health_indicators": DashboardSummaryService.get_health_indicators(),
                "user_activity": DashboardSummaryService.get_user_activity(days),
                "performance_indicators": DashboardSummaryService.get_performance_indicators(),
                "trend_data": DashboardSummaryService.get_trend_data(days),
                "distribution_stats": DashboardSummaryService.get_distribution_stats(),
            }

            return Response(summary_data)

        except Exception as e:
            logger.error(f"Error in system_summary: {str(e)}")
            return Response(
                {"error": "Failed to fetch system summary"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
