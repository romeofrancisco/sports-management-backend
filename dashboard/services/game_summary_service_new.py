from django.db.models import Count, Q, Avg, Sum, F, Max, Min
from django.utils import timezone
from datetime import datetime, timedelta
from games.models import Game, PlayerStat, GameSet
from users.models import User
from teams.models import Team


class GameSummaryService:
    """
    Service for providing game summary data for dashboard visualization.
    Focuses on high-level metrics and trends suitable for dashboard consumption.
    """
    
    @staticmethod
    def get_game_overview(days=30):
        """
        Get high-level game metrics for dashboard overview.
        
        Args:
            days (int): Number of days to look back for metrics
            
        Returns:
            dict: Game overview data
        """
        cutoff_date = timezone.now() - timedelta(days=days)
        
        try:
            # Basic counts
            total_games = Game.objects.count()
            recent_games = Game.objects.filter(
                date__gte=cutoff_date.date()
            ).count()
            
            completed_games = Game.objects.filter(
                date__gte=cutoff_date.date(),
                status='completed'
            ).count()
            
            upcoming_games = Game.objects.filter(
                date__gt=timezone.now().date(),
                date__lte=timezone.now().date() + timedelta(days=7)
            ).count()
            
            # Game completion rate
            completion_rate = (
                completed_games / recent_games * 100 
                if recent_games > 0 else 0
            )
            
            # Player stats metrics (as participation indicator)
            total_player_stats = PlayerStat.objects.filter(
                game__date__gte=cutoff_date.date()
            ).count()
            
            unique_participants = PlayerStat.objects.filter(
                game__date__gte=cutoff_date.date()
            ).values('player').distinct().count()
            
            # Average game duration (if available)
            avg_duration = Game.objects.filter(
                date__gte=cutoff_date.date(),
                status='completed',
                duration__isnull=False
            ).aggregate(avg_duration=Avg('duration'))['avg_duration']
            
            # Team participation
            active_teams = Team.objects.filter(
                Q(home_games__date__gte=cutoff_date.date()) |
                Q(away_games__date__gte=cutoff_date.date())
            ).distinct().count()
            
            return {
                'total_games': total_games,
                'recent_games': recent_games,
                'completed_games': completed_games,
                'upcoming_games': upcoming_games,
                'completion_rate': round(completion_rate, 1),
                'total_player_stats': total_player_stats,
                'unique_participants': unique_participants,
                'avg_duration': round(float(avg_duration.total_seconds() / 60), 1) if avg_duration else 0,
                'active_teams': active_teams,
                'period_days': days
            }
            
        except Exception as e:
            return {
                'total_games': 0,
                'recent_games': 0,
                'completed_games': 0,
                'upcoming_games': 0,
                'completion_rate': 0,
                'total_player_stats': 0,
                'unique_participants': 0,
                'avg_duration': 0,
                'active_teams': 0,
                'period_days': days,
                'error': str(e)
            }
    
    @staticmethod
    def get_weekly_trends(weeks=8):
        """
        Get weekly game trends for chart visualization.
        
        Args:
            weeks (int): Number of weeks to analyze
            
        Returns:
            dict: Weekly trend data
        """
        try:
            end_date = timezone.now().date()
            start_date = end_date - timedelta(weeks=weeks)
            
            # Weekly game counts
            weekly_data = []
            for week in range(weeks):
                week_start = start_date + timedelta(weeks=week)
                week_end = week_start + timedelta(days=6)
                
                week_participants = PlayerStat.objects.filter(
                    game__date__gte=week_start,
                    game__date__lte=week_end
                ).values('player').distinct().count()
                
                weekly_data.append({
                    'week_start': week_start.strftime('%Y-%m-%d'),
                    'week_end': week_end.strftime('%Y-%m-%d'),
                    'games_count': Game.objects.filter(
                        date__gte=week_start,
                        date__lte=week_end
                    ).count(),
                    'completed_games': Game.objects.filter(
                        date__gte=week_start,
                        date__lte=week_end,
                        status='completed'
                    ).count(),
                    'participants': week_participants
                })
            
            # Calculate trends
            if len(weekly_data) >= 2:
                recent_avg = sum(week['games_count'] for week in weekly_data[-2:]) / 2
                previous_avg = sum(week['games_count'] for week in weekly_data[:2]) / 2
                trend_percentage = ((recent_avg - previous_avg) / previous_avg * 100) if previous_avg > 0 else 0
            else:
                trend_percentage = 0
            
            return {
                'weekly_data': weekly_data,
                'trend_percentage': round(trend_percentage, 1),
                'weeks_analyzed': weeks
            }
            
        except Exception as e:
            return {
                'weekly_data': [],
                'trend_percentage': 0,
                'weeks_analyzed': weeks,
                'error': str(e)
            }
    
    @staticmethod
    def get_performance_indicators():
        """
        Get key performance indicators for games.
        
        Returns:
            dict: Performance indicator data
        """
        try:
            # Game completion metrics
            total_games = Game.objects.count()
            completed_games = Game.objects.filter(status='completed').count()
            in_progress_games = Game.objects.filter(status='in_progress').count()
            
            completion_rate = (completed_games / total_games * 100) if total_games > 0 else 0
            
            # Average scores
            avg_home_score = Game.objects.filter(
                status='completed'
            ).aggregate(avg_score=Avg('home_team_score'))['avg_score'] or 0
            
            avg_away_score = Game.objects.filter(
                status='completed'
            ).aggregate(avg_score=Avg('away_team_score'))['avg_score'] or 0
            
            # Player statistics metrics
            total_stats_recorded = PlayerStat.objects.count()
            avg_stats_per_game = PlayerStat.objects.values('game').annotate(
                stats_count=Count('id')
            ).aggregate(avg_stats=Avg('stats_count'))['avg_stats'] or 0
            
            # Game duration metrics
            avg_duration = Game.objects.filter(
                status='completed',
                duration__isnull=False
            ).aggregate(avg_duration=Avg('duration'))['avg_duration']
            
            return {
                'total_games': total_games,
                'completed_games': completed_games,
                'in_progress_games': in_progress_games,
                'completion_rate': round(completion_rate, 1),
                'avg_home_score': round(float(avg_home_score), 1),
                'avg_away_score': round(float(avg_away_score), 1),
                'total_stats_recorded': total_stats_recorded,
                'avg_stats_per_game': round(float(avg_stats_per_game), 1),
                'avg_duration_minutes': round(float(avg_duration.total_seconds() / 60), 1) if avg_duration else 0
            }
            
        except Exception as e:
            return {
                'total_games': 0,
                'completed_games': 0,
                'in_progress_games': 0,
                'completion_rate': 0,
                'avg_home_score': 0,
                'avg_away_score': 0,
                'total_stats_recorded': 0,
                'avg_stats_per_game': 0,
                'avg_duration_minutes': 0,
                'error': str(e)
            }
    
    @staticmethod
    def get_game_statistics_summary():
        """
        Get summary of game statistics for dashboard charts.
        
        Returns:
            dict: Game statistics summary
        """
        try:
            # Score distribution
            score_ranges = [
                (0, 20, 'Low Scoring'),
                (21, 50, 'Medium Scoring'),
                (51, 100, 'High Scoring'),
                (101, float('inf'), 'Very High Scoring')
            ]
            
            score_distribution = []
            for min_score, max_score, label in score_ranges:
                if max_score == float('inf'):
                    count = Game.objects.filter(
                        status='completed',
                        home_team_score__gte=min_score
                    ).count()
                else:
                    count = Game.objects.filter(
                        status='completed',
                        home_team_score__gte=min_score,
                        home_team_score__lte=max_score
                    ).count()
                
                score_distribution.append({
                    'range': label,
                    'count': count
                })
            
            # Game types distribution
            game_types = Game.objects.values('type').annotate(
                count=Count('id')
            ).order_by('-count')
            
            # Status distribution
            status_distribution = Game.objects.values('status').annotate(
                count=Count('id')
            ).order_by('-count')
            
            # Top teams by games played
            team_activity = Team.objects.annotate(
                games_played=Count('home_games') + Count('away_games')
            ).order_by('-games_played')[:10]
            
            team_activity_data = [{
                'team_name': team.name,
                'games_played': team.games_played
            } for team in team_activity]
            
            return {
                'score_distribution': score_distribution,
                'game_types': list(game_types),
                'status_distribution': list(status_distribution),
                'team_activity': team_activity_data
            }
            
        except Exception as e:
            return {
                'score_distribution': [],
                'game_types': [],
                'status_distribution': [],
                'team_activity': [],
                'error': str(e)
            }
    
    @staticmethod
    def get_recent_activity(limit=10):
        """
        Get recent game activity for dashboard feed.
        
        Args:
            limit (int): Number of recent activities to return
            
        Returns:
            dict: Recent activity data
        """
        try:
            recent_games = Game.objects.select_related(
                'home_team', 'away_team', 'sport'
            ).order_by('-date')[:limit]
            
            activities = []
            for game in recent_games:
                activity_data = {
                    'id': game.id,
                    'type': 'game',
                    'date': game.date.strftime('%Y-%m-%d %H:%M') if game.date else 'TBD',
                    'title': f"{game.home_team.name} vs {game.away_team.name}",
                    'status': game.status,
                    'sport': game.sport.name,
                    'home_score': game.home_team_score,
                    'away_score': game.away_team_score,
                    'location': game.location or 'TBD',
                }
                
                # Add stats count if available
                stats_count = PlayerStat.objects.filter(game=game).count()
                if stats_count > 0:
                    activity_data['stats_recorded'] = stats_count
                
                activities.append(activity_data)
            
            return {
                'activities': activities,
                'total_activities': len(activities)
            }
            
        except Exception as e:
            return {
                'activities': [],
                'total_activities': 0,
                'error': str(e)
            }
    
    @staticmethod
    def get_game_health_indicators():
        """
        Get health indicators for the game management system.
        
        Returns:
            dict: Health indicator data
        """
        try:
            # Recent activity check
            last_week = timezone.now() - timedelta(days=7)
            recent_games = Game.objects.filter(date__gte=last_week).count()
            
            # Data quality checks
            games_with_duration = Game.objects.filter(
                status='completed',
                duration__isnull=False
            ).count()
            
            completed_games = Game.objects.filter(status='completed').count()
            duration_coverage = (games_with_duration / completed_games * 100) if completed_games > 0 else 0
            
            # Player engagement
            active_players = PlayerStat.objects.filter(
                timestamp__gte=last_week
            ).values('player').distinct().count()
            
            # System utilization
            games_this_month = Game.objects.filter(
                date__gte=timezone.now().replace(day=1)
            ).count()
            
            # Score consistency check (detect anomalies)
            avg_score = Game.objects.filter(
                status='completed'
            ).aggregate(
                avg_home=Avg('home_team_score'),
                avg_away=Avg('away_team_score')
            )
            
            return {
                'recent_activity_level': 'high' if recent_games > 10 else 'medium' if recent_games > 5 else 'low',
                'recent_games_count': recent_games,
                'data_quality_score': round(duration_coverage, 1),
                'active_players': active_players,
                'monthly_games': games_this_month,
                'avg_home_score': round(float(avg_score['avg_home'] or 0), 1),
                'avg_away_score': round(float(avg_score['avg_away'] or 0), 1),
                'system_status': 'healthy' if recent_games > 0 and duration_coverage > 50 else 'needs_attention'
            }
            
        except Exception as e:
            return {
                'recent_activity_level': 'unknown',
                'recent_games_count': 0,
                'data_quality_score': 0,
                'active_players': 0,
                'monthly_games': 0,
                'avg_home_score': 0,
                'avg_away_score': 0,
                'system_status': 'error',
                'error': str(e)
            }
