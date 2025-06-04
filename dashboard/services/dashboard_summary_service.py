"""
Dashboard Summary Service
Provides aggregated summary data for the main dashboard
"""

from django.db.models import Count, Avg, Q, Sum
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from teams.models import Team, Player, Coach
from leagues.models import League, Season
from games.models import Game
from trainings.models import TrainingSession, PlayerTraining, PlayerMetricRecord
from sports.models import Sport


class DashboardSummaryService:
    """Service for providing dashboard summary data and key metrics"""
    
    def __init__(self, user=None):
        self.user = user
        self.last_30_days = timezone.now() - timedelta(days=30)
        self.last_7_days = timezone.now() - timedelta(days=7)
    
    def get_system_overview(self):
        """Get high-level system overview metrics"""
        
        # Core counts
        total_teams = Team.objects.count()
        total_players = Player.objects.filter(team__isnull=False).count()
        total_coaches = Coach.objects.count()
        total_leagues = League.objects.count()
        total_sports = Sport.objects.count()
        
        # Health indicators
        unassigned_players = Player.objects.filter(team__isnull=True).count()
        teams_without_coaches = Team.objects.filter(coaches__isnull=True).distinct().count()
        teams_with_few_players = Team.objects.annotate(
            player_count=Count('players')
        ).filter(player_count__lt=8).count()
        
        # Activity metrics (last 30 days)
        recent_games = Game.objects.filter(date__gte=self.last_30_days.date()).count()
        recent_training_sessions = TrainingSession.objects.filter(
            date__gte=self.last_30_days.date()
        ).count()
        
        # Active leagues
        active_leagues = League.objects.filter(
            seasons__status__in=['ongoing', 'upcoming']
        ).distinct().count()
        
        return {
            'core_metrics': {
                'total_teams': total_teams,
                'total_players': total_players,
                'total_coaches': total_coaches,
                'total_leagues': total_leagues,
                'total_sports': total_sports,
                'active_leagues': active_leagues
            },
            'health_indicators': {
                'unassigned_players': unassigned_players,
                'teams_without_coaches': teams_without_coaches,
                'teams_with_few_players': teams_with_few_players,
                'health_score': self._calculate_health_score(
                    total_teams, teams_without_coaches, 
                    teams_with_few_players, unassigned_players
                )
            },
            'activity_summary': {
                'recent_games': recent_games,
                'recent_training_sessions': recent_training_sessions,
                'games_per_day': round(recent_games / 30, 1),
                'training_sessions_per_day': round(recent_training_sessions / 30, 1)
            }
        }
    
    def get_user_activity_summary(self):
        """Get user activity and engagement metrics"""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        # User counts
        total_users = User.objects.count()
        active_users_week = User.objects.filter(
            last_login__gte=self.last_7_days
        ).count()
        new_users_month = User.objects.filter(
            date_joined__gte=self.last_30_days
        ).count()
        
        # Role distribution
        admin_count = User.objects.filter(roles__contains=['admin']).count()
        coach_count = User.objects.filter(roles__contains=['coach']).count()
        player_count = User.objects.filter(roles__contains=['player']).count()
        
        return {
            'user_metrics': {
                'total_users': total_users,
                'active_users_week': active_users_week,
                'new_users_month': new_users_month,
                'engagement_rate': round(
                    (active_users_week / total_users * 100) if total_users > 0 else 0, 1
                )
            },
            'role_distribution': {
                'admins': admin_count,
                'coaches': coach_count,
                'players': player_count,
                'other': total_users - admin_count - coach_count - player_count
            }
        }
    
    def get_performance_indicators(self):
        """Get key performance indicators across the system"""
        
        # Training performance
        total_training_records = PlayerTraining.objects.count()
        present_records = PlayerTraining.objects.filter(
            attendance_status='present'
        ).count()
        training_attendance_rate = (
            (present_records / total_training_records * 100) 
            if total_training_records > 0 else 0
        )
        
        # Game completion rate
        completed_games = Game.objects.filter(status='completed').count()
        total_games = Game.objects.count()
        game_completion_rate = (
            (completed_games / total_games * 100) 
            if total_games > 0 else 0
        )
        
        # League activity
        leagues_with_activity = League.objects.filter(
            Q(seasons__games__date__gte=self.last_30_days.date()) |
            Q(seasons__team_seasons__team__training_sessions__date__gte=self.last_30_days.date())
        ).distinct().count()
        total_leagues = League.objects.count()
        league_activity_rate = (
            (leagues_with_activity / total_leagues * 100) 
            if total_leagues > 0 else 0
        )
        
        return {
            'training_performance': {
                'attendance_rate': round(training_attendance_rate, 1),
                'total_records': total_training_records,
                'present_count': present_records
            },
            'game_performance': {
                'completion_rate': round(game_completion_rate, 1),
                'completed_games': completed_games,
                'total_games': total_games
            },
            'league_performance': {
                'activity_rate': round(league_activity_rate, 1),
                'active_leagues': leagues_with_activity,
                'total_leagues': total_leagues
            },
            'overall_score': round(
                (training_attendance_rate + game_completion_rate + league_activity_rate) / 3, 1
            )
        }
    
    def get_trend_data(self, days=30):
        """Get trend data for charts over specified period"""
        
        # Calculate date range
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days)
        
        # Daily activity trends
        daily_trends = []
        current_date = start_date
        
        while current_date <= end_date:
            games_count = Game.objects.filter(date=current_date).count()
            training_count = TrainingSession.objects.filter(date=current_date).count()
            
            daily_trends.append({
                'date': current_date.isoformat(),
                'games': games_count,
                'training_sessions': training_count,
                'total_activity': games_count + training_count
            })
            
            current_date += timedelta(days=1)
        
        return {
            'daily_trends': daily_trends,
            'period_summary': {
                'total_days': days,
                'avg_daily_games': round(
                    sum(day['games'] for day in daily_trends) / days, 1
                ),
                'avg_daily_training': round(
                    sum(day['training_sessions'] for day in daily_trends) / days, 1
                )
            }
        }
    
    def get_distribution_stats(self):
        """Get distribution statistics for various entities"""
        
        # Teams by sport
        teams_by_sport = list(
            Team.objects.values('sport__name')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        
        # Players by sport
        players_by_sport = list(
            Player.objects.filter(team__isnull=False)
            .values('team__sport__name')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        
        # Teams by division
        teams_by_division = list(
            Team.objects.values('division')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        
        # Recent metric records by sport
        recent_metrics = list(
            PlayerMetricRecord.objects.filter(
                recorded_at__gte=self.last_30_days
            ).values('player_training__player__team__sport__name')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        
        return {
            'sport_distribution': {
                'teams': teams_by_sport,
                'players': players_by_sport,
                'recent_metrics': recent_metrics
            },
            'division_distribution': teams_by_division,
            'activity_distribution': self._get_activity_distribution()
        }
    
    def _calculate_health_score(self, total_teams, teams_without_coaches, 
                              teams_with_few_players, unassigned_players):
        """Calculate system health score (0-100)"""
        
        if total_teams == 0:
            return 50
        
        # Penalties for health issues
        coach_penalty = (teams_without_coaches / total_teams) * 30
        player_penalty = (teams_with_few_players / total_teams) * 20
        unassigned_penalty = min((unassigned_players / 50) * 25, 25)
        
        health_score = 100 - coach_penalty - player_penalty - unassigned_penalty
        return max(0, min(100, round(health_score)))
    
    def _get_activity_distribution(self):
        """Get activity distribution across teams"""
        
        # Teams with recent activity
        teams_with_games = Team.objects.filter(
            Q(home_games__date__gte=self.last_30_days.date()) |
            Q(away_games__date__gte=self.last_30_days.date())
        ).distinct().count()
        
        teams_with_training = Team.objects.filter(
            training_sessions__date__gte=self.last_30_days.date()
        ).distinct().count()
        
        total_teams = Team.objects.count()
        
        return {
            'teams_with_games': teams_with_games,
            'teams_with_training': teams_with_training,
            'teams_with_any_activity': Team.objects.filter(
                Q(home_games__date__gte=self.last_30_days.date()) |
                Q(away_games__date__gte=self.last_30_days.date()) |
                Q(training_sessions__date__gte=self.last_30_days.date())
            ).distinct().count(),
            'inactive_teams': total_teams - Team.objects.filter(
                Q(home_games__date__gte=self.last_30_days.date()) |
                Q(away_games__date__gte=self.last_30_days.date()) |
                Q(training_sessions__date__gte=self.last_30_days.date())
            ).distinct().count()
        }
