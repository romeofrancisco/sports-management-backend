from django.db.models import Count, Q, Avg, Sum, F, Max
from django.utils import timezone
from datetime import datetime, timedelta
from leagues.models import League, Season
from games.models import Game, GameSet
from users.models import User
from teams.models import Team


class LeagueSummaryService:
    """
    Service for providing league summary data for dashboard visualization.
    Focuses on high-level metrics and trends suitable for dashboard consumption.
    """
    
    @staticmethod
    def get_league_overview(days=30):
        """
        Get high-level league metrics for dashboard overview.
        
        Args:
            days (int): Number of days to look back for metrics
            
        Returns:
            dict: League overview data
        """
        cutoff_date = timezone.now() - timedelta(days=days)
        
        try:
            # Basic counts
            total_leagues = League.objects.count()
            active_seasons = Season.objects.filter(
                status='ongoing'
            ).count()
            
            recent_games = Game.objects.filter(
                date__gte=cutoff_date.date()
            ).count()
            
            # League participation metrics
            total_teams = Team.objects.filter(
                leagues__isnull=False
            ).distinct().count()
            
            # Game completion metrics
            completed_games = Game.objects.filter(
                date__gte=cutoff_date.date(),
                status='completed'
            ).count()
            
            completion_rate = round(
                (completed_games / recent_games * 100) if recent_games > 0 else 0, 1
            )
            
            # Average games per season
            avg_games_per_season = Game.objects.filter(
                season__start_date__lte=timezone.now().date(),
                season__end_date__gte=timezone.now().date()
            ).values('season').annotate(
                game_count=Count('id')
            ).aggregate(
                avg_games=Avg('game_count')
            )['avg_games'] or 0
            
            return {
                'total_leagues': total_leagues,
                'active_seasons': active_seasons,
                'recent_games': recent_games,
                'completed_games': completed_games,
                'completion_rate': completion_rate,
                'total_teams': total_teams,
                'avg_games_per_season': round(float(avg_games_per_season), 1),
                'period_days': days
            }
            
        except Exception as e:
            return {
                'total_leagues': 0,
                'active_seasons': 0,
                'recent_games': 0,
                'completed_games': 0,
                'completion_rate': 0,
                'total_teams': 0,
                'avg_games_per_season': 0,
                'period_days': days,
                'error': str(e)
            }
    
    @staticmethod
    def get_league_trends(days=30):
        """
        Get league trends data for chart visualization.
        
        Args:
            days (int): Number of days to analyze
            
        Returns:
            dict: Trend data suitable for charts
        """
        cutoff_date = timezone.now() - timedelta(days=days)
        
        try:
            # Daily game counts
            daily_games = Game.objects.filter(
                date__gte=cutoff_date.date()
            ).extra(
                select={'day': 'DATE(date)'}
            ).values('day').annotate(
                game_count=Count('id'),
                completed_count=Count('id', filter=Q(status='completed'))
            ).order_by('day')
            
            # League activity over time
            weekly_activity = []
            for week in range(0, days, 7):
                week_start = timezone.now() - timedelta(days=week+7)
                week_end = timezone.now() - timedelta(days=week)
                
                week_games = Game.objects.filter(
                    date__range=[week_start.date(), week_end.date()]
                ).count()
                
                week_completed = Game.objects.filter(
                    date__range=[week_start.date(), week_end.date()],
                    status='completed'
                ).count()
                
                completion_rate = (
                    week_completed / week_games * 100 
                    if week_games > 0 else 0
                )
                
                weekly_activity.append({
                    'week': f"Week {week//7 + 1}",
                    'games': week_games,
                    'completed': week_completed,
                    'completion_rate': round(completion_rate, 1),
                    'week_start': week_start.date().isoformat(),
                    'week_end': week_end.date().isoformat()
                })
            
            # Sport distribution
            sport_distribution = League.objects.values(
                'sport__name'
            ).annotate(
                league_count=Count('id'),
                team_count=Count('seasons__teams', distinct=True),
                game_count=Count('seasons__games')
            ).order_by('-league_count')
            
            # Season status distribution
            season_status = Season.objects.values(
                'status'
            ).annotate(
                count=Count('id')
            ).order_by('-count')
            
            return {
                'daily_games': list(daily_games),
                'weekly_activity': weekly_activity,
                'sport_distribution': list(sport_distribution),
                'season_status': list(season_status),
                'period_days': days
            }
            
        except Exception as e:
            return {
                'daily_games': [],
                'weekly_activity': [],
                'sport_distribution': [],
                'season_status': [],
                'period_days': days,
                'error': str(e)
            }
    
    @staticmethod
    def get_league_performance(days=30):
        """
        Get league performance metrics for dashboard.
        
        Args:
            days (int): Number of days to analyze
            
        Returns:
            dict: Performance metrics
        """
        cutoff_date = timezone.now() - timedelta(days=days)
        
        try:
            # Top performing leagues by activity
            top_leagues = League.objects.annotate(
                total_games=Count('seasons__games'),
                recent_games=Count(
                    'seasons__games',
                    filter=Q(seasons__games__date__gte=cutoff_date.date())
                ),
                participating_teams=Count('seasons__teams', distinct=True),
                active_seasons=Count('seasons', filter=Q(seasons__status='ongoing'))
            ).order_by('-recent_games')[:5]
            
            # Season performance metrics
            season_performance = Season.objects.filter(
                start_date__gte=cutoff_date.date()
            ).annotate(
                total_games=Count('games'),
                completed_games=Count('games', filter=Q(games__status='completed')),
                completion_rate=F('completed_games') * 100.0 / F('total_games'),
                participating_teams=Count('teams')
            ).order_by('-completion_rate')[:5]
            
            # League engagement metrics
            engagement_stats = {
                'leagues_with_active_seasons': League.objects.filter(
                    seasons__status='ongoing'
                ).distinct().count(),
                'games_this_week': Game.objects.filter(
                    date__gte=timezone.now().date() - timedelta(days=7)
                ).count(),
                'avg_teams_per_league': League.objects.annotate(
                    team_count=Count('seasons__teams', distinct=True)
                ).aggregate(
                    avg_teams=Avg('team_count')
                )['avg_teams'] or 0,
                'upcoming_games': Game.objects.filter(
                    date__gt=timezone.now().date(),
                    date__lte=timezone.now().date() + timedelta(days=7)
                ).count()
            }
            
            return {
                'top_leagues': [
                    {
                        'id': league.id,
                        'name': league.name,
                        'sport': league.sport.name if league.sport else 'N/A',
                        'total_games': league.total_games,
                        'recent_games': league.recent_games,
                        'participating_teams': league.participating_teams,
                        'active_seasons': league.active_seasons
                    }
                    for league in top_leagues
                ],
                'season_performance': [
                    {
                        'id': season.id,
                        'name': season.name,
                        'league': season.league.name,
                        'total_games': season.total_games,
                        'completed_games': season.completed_games,
                        'completion_rate': round(float(season.completion_rate or 0), 1),
                        'participating_teams': season.participating_teams
                    }
                    for season in season_performance
                ],
                'engagement_stats': engagement_stats,
                'period_days': days
            }
            
        except Exception as e:
            return {
                'top_leagues': [],
                'season_performance': [],
                'engagement_stats': {
                    'leagues_with_active_seasons': 0,
                    'games_this_week': 0,
                    'avg_teams_per_league': 0,
                    'upcoming_games': 0
                },
                'period_days': days,
                'error': str(e)
            }
    
    @staticmethod
    def get_league_health_indicators():
        """
        Get league health indicators for dashboard alerts.
        
        Returns:
            dict: Health indicators and alerts
        """
        try:
            now = timezone.now()
            
            # Leagues without recent activity
            inactive_leagues = League.objects.exclude(
                seasons__games__date__gte=now.date() - timedelta(days=14)
            ).distinct().count()
            
            # Seasons without games scheduled
            seasons_without_games = Season.objects.filter(
                status__in=['ongoing', 'upcoming'],
                start_date__lte=now.date() + timedelta(days=30)
            ).annotate(
                game_count=Count('games')
            ).filter(game_count=0).count()
            
            # Overdue games
            overdue_games = Game.objects.filter(
                date__lt=now.date(),
                status__in=['scheduled', 'pending']
            ).count()
            
            # Leagues with insufficient teams
            leagues_insufficient_teams = League.objects.annotate(
                team_count=Count('seasons__teams', distinct=True)
            ).filter(team_count__lt=2).count()
            
            # Calculate health score (0-100)
            total_leagues = League.objects.count()
            
            if total_leagues == 0:
                health_score = 100
            else:
                inactive_penalty = (inactive_leagues / total_leagues) * 25
                insufficient_teams_penalty = (leagues_insufficient_teams / total_leagues) * 30
                overdue_penalty = min(overdue_games * 2, 25)
                no_games_penalty = min(seasons_without_games * 5, 20)
                
                health_score = max(0, 100 - inactive_penalty - insufficient_teams_penalty - 
                                 overdue_penalty - no_games_penalty)
            
            # Determine health status
            if health_score >= 80:
                health_status = 'excellent'
            elif health_score >= 60:
                health_status = 'good'
            elif health_score >= 40:
                health_status = 'fair'
            else:
                health_status = 'poor'
            
            # Generate alerts
            alerts = []
            if inactive_leagues > 0:
                alerts.append({
                    'type': 'warning',
                    'message': f"{inactive_leagues} leagues without recent activity"
                })
            if overdue_games > 0:
                alerts.append({
                    'type': 'error',
                    'message': f"{overdue_games} overdue games need attention"
                })
            if leagues_insufficient_teams > 0:
                alerts.append({
                    'type': 'warning',
                    'message': f"{leagues_insufficient_teams} leagues have insufficient teams"
                })
            if seasons_without_games > 0:
                alerts.append({
                    'type': 'info',
                    'message': f"{seasons_without_games} seasons have no scheduled games"
                })
            
            return {
                'health_score': round(health_score, 1),
                'health_status': health_status,
                'indicators': {
                    'inactive_leagues': inactive_leagues,
                    'seasons_without_games': seasons_without_games,
                    'overdue_games': overdue_games,
                    'leagues_insufficient_teams': leagues_insufficient_teams,
                    'total_leagues': total_leagues
                },
                'alerts': alerts
            }
            
        except Exception as e:
            return {
                'health_score': 0,
                'health_status': 'unknown',
                'indicators': {
                    'inactive_leagues': 0,
                    'seasons_without_games': 0,
                    'overdue_games': 0,
                    'leagues_insufficient_teams': 0,
                    'total_leagues': 0
                },
                'alerts': [],
                'error': str(e)
            }
