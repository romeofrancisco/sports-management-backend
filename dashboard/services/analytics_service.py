from django.db.models import Count, Q, Avg, Sum, F, Max, Min
from django.utils import timezone
from datetime import datetime, timedelta
from collections import defaultdict
import json

from users.models import User
from teams.models import Team
from sports.models import Sport
from trainings.models import TrainingSession, PlayerTraining
from leagues.models import League, Season
from games.models import Game, PlayerStat


class AnalyticsService:
    """
    Service for providing advanced analytics and chart data for dashboard visualization.
    Handles complex data processing for charts, trends, and comparative analytics.
    """
    
    @staticmethod
    def get_engagement_analytics(days=30):
        """
        Get comprehensive engagement analytics across all modules.
        
        Args:
            days (int): Number of days to analyze
            
        Returns:
            dict: Engagement analytics data
        """
        cutoff_date = timezone.now() - timedelta(days=days)
        
        try:
            # User engagement across modules
            user_engagement = User.objects.annotate(
                training_sessions=Count(
                    'playertraining_set',
                    filter=Q(playertraining_set__training_session__date__gte=cutoff_date.date())
                ),
                games_played=Count(
                    'player__player_stats',
                    filter=Q(player__player_stats__game__date__gte=cutoff_date.date()),
                    distinct=True
                ),
                leagues_participated=Count(
                    'player__team__league',
                    filter=Q(player__team__league__is_active=True),
                    distinct=True
                )
            ).filter(
                Q(training_sessions__gt=0) |
                Q(games_played__gt=0) |
                Q(leagues_participated__gt=0)
            )
            
            # Module activity summary
            module_activity = {
                'trainings': PlayerTraining.objects.filter(
                    training_session__date__gte=cutoff_date.date()
                ).count(),
                'games': PlayerStat.objects.filter(
                    game__date__gte=cutoff_date.date()
                ).values('game').distinct().count(),
                'leagues': League.objects.filter(is_active=True).count(),
                'active_users': user_engagement.count()
            }
            
            # Daily activity breakdown
            daily_activity = []
            for i in range(days):
                day_date = timezone.now() - timedelta(days=i)
                
                training_activity = PlayerTraining.objects.filter(
                    training_session__date=day_date.date()
                ).count()
                
                game_activity = PlayerStat.objects.filter(
                    game__date=day_date.date()
                ).values('game').distinct().count()
                
                daily_activity.append({
                    'date': day_date.strftime('%Y-%m-%d'),
                    'trainings': training_activity,
                    'games': game_activity,
                    'total': training_activity + game_activity
                })
            
            # Engagement trends
            engagement_data = list(user_engagement.values(
                'id', 'username', 'training_sessions', 'games_played', 'leagues_participated'
            ))
            
            return {
                'module_activity': module_activity,
                'daily_activity': daily_activity[::-1],  # Reverse to show chronologically
                'user_engagement': engagement_data,
                'total_engaged_users': len(engagement_data),
                'period_days': days
            }
            
        except Exception as e:
            return {
                'module_activity': {},
                'daily_activity': [],
                'user_engagement': [],
                'total_engaged_users': 0,
                'period_days': days,
                'error': str(e)
            }
    
    @staticmethod
    def get_comparative_analytics():
        """
        Get comparative analytics between different sports, teams, and time periods.
        
        Returns:
            dict: Comparative analytics data
        """
        try:
            # Sport popularity comparison
            sport_metrics = Sport.objects.annotate(
                total_games=Count('game_set'),
                total_teams=Count('team_set'),
                total_leagues=Count('league_set'),
                active_players=Count('team_set__players', distinct=True)
            ).order_by('-total_games')
            
            sport_comparison = [{
                'sport_name': sport.name,
                'total_games': sport.total_games,
                'total_teams': sport.total_teams,
                'total_leagues': sport.total_leagues,
                'active_players': sport.active_players
            } for sport in sport_metrics]
            
            # Team performance comparison
            team_metrics = Team.objects.annotate(
                games_played=Count('home_games') + Count('away_games'),
                games_won=Count('games_won'),
                avg_home_score=Avg('home_games__home_team_score'),
                avg_away_score=Avg('away_games__away_team_score'),
                player_count=Count('players')
            ).filter(games_played__gt=0).order_by('-games_won')[:10]
            
            team_comparison = [{
                'team_name': team.name,
                'games_played': team.games_played,
                'games_won': team.games_won,
                'win_rate': round((team.games_won / team.games_played * 100), 1) if team.games_played > 0 else 0,
                'avg_home_score': round(float(team.avg_home_score or 0), 1),
                'avg_away_score': round(float(team.avg_away_score or 0), 1),
                'player_count': team.player_count
            } for team in team_metrics]
            
            # League activity comparison
            league_metrics = League.objects.annotate(
                total_games=Count('game_set'),
                total_teams=Count('league_teams__team', distinct=True),
                total_seasons=Count('season_set')
            ).order_by('-total_games')
            
            league_comparison = [{
                'league_name': league.name,
                'total_games': league.total_games,
                'total_teams': league.total_teams,
                'total_seasons': league.total_seasons,
                'is_active': league.is_active
            } for league in league_metrics]
            
            # Monthly comparison (last 6 months)
            monthly_data = []
            for i in range(6):
                month_start = (timezone.now().replace(day=1) - timedelta(days=32*i)).replace(day=1)
                month_end = (month_start.replace(month=month_start.month % 12 + 1) if month_start.month < 12 
                           else month_start.replace(year=month_start.year + 1, month=1)) - timedelta(days=1)
                
                games = Game.objects.filter(date__range=[month_start, month_end]).count()
                trainings = TrainingSession.objects.filter(date__range=[month_start, month_end]).count()
                
                monthly_data.append({
                    'month': month_start.strftime('%Y-%m'),
                    'games': games,
                    'trainings': trainings,
                    'total_activities': games + trainings
                })
            
            return {
                'sport_comparison': sport_comparison,
                'team_comparison': team_comparison,
                'league_comparison': league_comparison,
                'monthly_comparison': monthly_data[::-1]  # Reverse for chronological order
            }
            
        except Exception as e:
            return {
                'sport_comparison': [],
                'team_comparison': [],
                'league_comparison': [],
                'monthly_comparison': [],
                'error': str(e)
            }
    
    @staticmethod
    def get_growth_analytics(months=12):
        """
        Get growth analytics and trends over time.
        
        Args:
            months (int): Number of months to analyze
            
        Returns:
            dict: Growth analytics data
        """
        try:
            growth_data = []
            
            for i in range(months):
                month_date = timezone.now().replace(day=1) - timedelta(days=32*i)
                month_start = month_date.replace(day=1)
                month_end = (month_start.replace(month=month_start.month % 12 + 1) if month_start.month < 12 
                           else month_start.replace(year=month_start.year + 1, month=1)) - timedelta(days=1)
                
                # Count new registrations/creations
                new_users = User.objects.filter(
                    date_joined__range=[month_start, month_end]
                ).count()
                
                new_teams = Team.objects.filter(
                    created_at__range=[month_start, month_end]
                ).count()
                
                new_leagues = League.objects.filter(
                    created_at__range=[month_start, month_end]
                ).count()
                
                # Activity metrics
                games_count = Game.objects.filter(
                    date__range=[month_start, month_end]
                ).count()
                
                training_count = TrainingSession.objects.filter(
                    date__range=[month_start, month_end]
                ).count()
                
                growth_data.append({
                    'month': month_start.strftime('%Y-%m'),
                    'new_users': new_users,
                    'new_teams': new_teams,
                    'new_leagues': new_leagues,
                    'games_conducted': games_count,
                    'training_sessions': training_count
                })
            
            # Calculate growth rates
            growth_rates = {}
            if len(growth_data) >= 2:
                latest = growth_data[0]
                previous = growth_data[1]
                
                for key in ['new_users', 'new_teams', 'new_leagues', 'games_conducted', 'training_sessions']:
                    if previous[key] > 0:
                        growth_rates[f'{key}_growth'] = round(
                            ((latest[key] - previous[key]) / previous[key] * 100), 1
                        )
                    else:
                        growth_rates[f'{key}_growth'] = 0
            
            return {
                'monthly_growth': growth_data[::-1],  # Reverse for chronological order
                'growth_rates': growth_rates,
                'months_analyzed': months
            }
            
        except Exception as e:
            return {
                'monthly_growth': [],
                'growth_rates': {},
                'months_analyzed': months,
                'error': str(e)
            }
    
    @staticmethod
    def get_activity_heatmap(days=30):
        """
        Get activity heatmap data for calendar visualization.
        
        Args:
            days (int): Number of days to analyze
            
        Returns:
            dict: Heatmap data
        """
        try:
            heatmap_data = []
            
            for i in range(days):
                day_date = timezone.now() - timedelta(days=i)
                
                # Get activity counts for each day
                games = Game.objects.filter(date=day_date.date()).count()
                trainings = TrainingSession.objects.filter(date=day_date.date()).count()
                
                # Calculate intensity based on total activities
                total_activity = games + trainings
                if total_activity >= 5:
                    intensity = 'high'
                elif total_activity >= 2:
                    intensity = 'medium'
                elif total_activity >= 1:
                    intensity = 'low'
                else:
                    intensity = 'none'
                
                heatmap_data.append({
                    'date': day_date.strftime('%Y-%m-%d'),
                    'day_of_week': day_date.strftime('%A'),
                    'games': games,
                    'trainings': trainings,
                    'total_activity': total_activity,
                    'intensity': intensity
                })
            
            # Day of week analysis
            dow_analysis = defaultdict(lambda: {'games': 0, 'trainings': 0, 'count': 0})
            for day in heatmap_data:
                dow = day['day_of_week']
                dow_analysis[dow]['games'] += day['games']
                dow_analysis[dow]['trainings'] += day['trainings']
                dow_analysis[dow]['count'] += 1
            
            # Calculate averages
            dow_averages = {}
            for dow, data in dow_analysis.items():
                dow_averages[dow] = {
                    'avg_games': round(data['games'] / data['count'], 1),
                    'avg_trainings': round(data['trainings'] / data['count'], 1),
                    'avg_total': round((data['games'] + data['trainings']) / data['count'], 1)
                }
            
            return {
                'heatmap_data': heatmap_data[::-1],  # Reverse for chronological order
                'day_of_week_analysis': dow_averages,
                'days_analyzed': days
            }
            
        except Exception as e:
            return {
                'heatmap_data': [],
                'day_of_week_analysis': {},
                'days_analyzed': days,
                'error': str(e)
            }
    
    @staticmethod
    def get_performance_analytics():
        """
        Get advanced performance analytics across all modules.
        
        Returns:
            dict: Performance analytics data
        """
        try:
            # Game performance metrics
            game_performance = {
                'total_games': Game.objects.count(),
                'completed_games': Game.objects.filter(status='completed').count(),
                'avg_game_duration': 0,
                'avg_score_differential': 0
            }
            
            # Calculate averages
            completed_games = Game.objects.filter(status='completed')
            if completed_games.exists():
                # Average duration
                durations = completed_games.filter(duration__isnull=False)
                if durations.exists():
                    avg_duration = durations.aggregate(Avg('duration'))['duration__avg']
                    game_performance['avg_game_duration'] = round(float(avg_duration.total_seconds() / 60), 1)
                
                # Average score differential
                score_diff = completed_games.aggregate(
                    avg_diff=Avg(F('home_team_score') - F('away_team_score'))
                )['avg_diff']
                game_performance['avg_score_differential'] = round(float(abs(score_diff or 0)), 1)
            
            # Training performance metrics
            training_performance = {
                'total_sessions': TrainingSession.objects.count(),
                'total_participants': PlayerTraining.objects.count(),
                'avg_participants_per_session': 0,
                'recent_activity': TrainingSession.objects.filter(
                    date__gte=timezone.now().date() - timedelta(days=7)
                ).count()
            }
            
            # Calculate training averages
            session_participants = TrainingSession.objects.annotate(
                participant_count=Count('playertraining_set')
            ).aggregate(avg_participants=Avg('participant_count'))['avg_participants']
            
            training_performance['avg_participants_per_session'] = round(float(session_participants or 0), 1)
            
            # League performance metrics
            league_performance = {
                'total_leagues': League.objects.count(),
                'active_leagues': League.objects.filter(is_active=True).count(),
                'avg_teams_per_league': 0,
                'avg_games_per_league': 0
            }
            
            # Calculate league averages
            league_stats = League.objects.annotate(
                team_count=Count('league_teams__team', distinct=True),
                game_count=Count('game_set')
            ).aggregate(
                avg_teams=Avg('team_count'),
                avg_games=Avg('game_count')
            )
            
            league_performance['avg_teams_per_league'] = round(float(league_stats['avg_teams'] or 0), 1)
            league_performance['avg_games_per_league'] = round(float(league_stats['avg_games'] or 0), 1)
            
            # Overall system metrics
            system_metrics = {
                'total_users': User.objects.count(),
                'total_teams': Team.objects.count(),
                'total_sports': Sport.objects.count(),
                'data_completeness': 0
            }
            
            # Calculate data completeness score
            total_entities = (
                game_performance['total_games'] +
                training_performance['total_sessions'] +
                league_performance['total_leagues']
            )
            
            entities_with_data = (
                Game.objects.filter(duration__isnull=False).count() +
                TrainingSession.objects.filter(playertraining_set__isnull=False).count() +
                League.objects.filter(game_set__isnull=False).count()
            )
            
            if total_entities > 0:
                system_metrics['data_completeness'] = round(
                    (entities_with_data / total_entities * 100), 1
                )
            
            return {
                'game_performance': game_performance,
                'training_performance': training_performance,
                'league_performance': league_performance,
                'system_metrics': system_metrics
            }
            
        except Exception as e:
            return {
                'game_performance': {},
                'training_performance': {},
                'league_performance': {},
                'system_metrics': {},
                'error': str(e)
            }
