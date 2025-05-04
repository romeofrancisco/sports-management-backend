from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import League, Season
from .serializers import LeagueSerializer, LeagueWriteSerializer, SeasonSerializer, TeamStandingsSerializer, LeagueStatisticsSerializer, SeasonComparisonSerializer
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum, Avg, F, Q
from teams.models import Team

class LeagueViewSet(viewsets.ModelViewSet):
    queryset = League.objects.all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return LeagueWriteSerializer
        return LeagueSerializer
    
    @action(detail=True, methods=["get"])
    def standings(self, request, pk=None):
        league = self.get_object()
        standings = league.standings(request=request)
        return Response(standings)
    
    @action(detail=True, methods=["get"])
    def statistics(self, request, pk=None):
        """Get comprehensive league statistics for the dashboard"""
        league = self.get_object()
        
        # Get all completed games in the league
        all_games = league.seasons.prefetch_related('games').filter(
            games__status="completed"
        )
        
        # Count teams, seasons, games
        teams_count = league.seasons.aggregate(
            total_teams=Count('teams', distinct=True)
        )['total_teams']
        
        seasons_count = league.seasons.count()
        active_seasons = league.seasons.filter(status__in=["ongoing", "upcoming"]).count()
        
        games_count = all_games.count()
        
        # Get current season if any
        current_season = league.seasons.filter(status="ongoing").order_by("-start_date").first()
        
        statistics = {
            "teams_count": teams_count,
            "seasons_count": seasons_count,
            "active_seasons": active_seasons,
            "games_count": games_count,
            "current_season": SeasonSerializer(current_season, context={"request": request}).data if current_season else None,
        }
        
        return Response(statistics)
    
    @action(detail=True, methods=["get"])
    def team_form(self, request, pk=None):
        """Get the recent form for top teams in the league"""
        league = self.get_object()
        limit = int(request.query_params.get('limit', 5))
        
        # Get top teams based on standings
        top_teams_data = league.standings(request=request)[:limit]
        top_team_ids = [team['team_id'] for team in top_teams_data]
        
        # Get all teams
        teams = Team.objects.filter(id__in=top_team_ids)
        
        # Get recent games for each team (last 5)
        results = {}
        
        for team in teams:
            from games.models import Game
            
            recent_games = Game.objects.filter(
                Q(home_team=team) | Q(away_team=team),
                season__league=league,
                status="completed"
            ).order_by('-date')[:5]  # Changed from scheduled_date to date
            
            team_results = []
            for game in recent_games:
                # Determine if team won, lost or tied
                if game.home_team == team:
                    if game.home_team_score > game.away_team_score:
                        result = 'W'
                    elif game.home_team_score < game.away_team_score:
                        result = 'L'
                    else:
                        result = 'D'
                    score = f"{game.home_team_score}-{game.away_team_score}"
                    opponent = game.away_team.name
                else:
                    if game.away_team_score > game.home_team_score:
                        result = 'W'
                    elif game.away_team_score < game.home_team_score:
                        result = 'L'
                    else:
                        result = 'D'
                    score = f"{game.away_team_score}-{game.home_team_score}"
                    opponent = game.home_team.name
                
                team_results.append({
                    'result': result,
                    'score': score,
                    'opponent': opponent,
                    'date': game.date.strftime("%Y-%m-%d")  # Changed from scheduled_date to date
                })
            
            results[team.id] = team_results
        
        return Response({
            'teams': top_teams_data,
            'form': results
        })
    
class SeasonViewSet(viewsets.ModelViewSet):
    serializer_class = SeasonSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        return Season.objects.filter(league_id=self.kwargs['league_pk'])

    def perform_create(self, serializer):
        league = get_object_or_404(League, pk=self.kwargs['league_pk'])
        serializer.save(league=league)
    
    @action(detail=True, methods=["post"])
    def manage(self, request, pk=None, **kwargs):
        season = self.get_object()
        action_type = request.data.get("action")

        try:
            if action_type == "start":
                season.start_season()
                return Response({"detail": "Season started."}, status=status.HTTP_200_OK)

            elif action_type == "complete":
                season.complete_season()
                return Response({"detail": "Season completed."}, status=status.HTTP_200_OK)

            elif action_type == "pause":
                season.pause_season()
                return Response({"detail": "Season paused."}, status=status.HTTP_200_OK)

            elif action_type == "cancel":
                season.cancel_season()
                return Response({"detail": "Season canceled."}, status=status.HTTP_200_OK)

            else:
                return Response({"detail": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)

        except ValidationError as e:
            return Response({"detail": e.message}, status=status.HTTP_400_BAD_REQUEST)
        
    @action(detail=True, methods=['post'])
    def add_team(self, request, pk=None):
        season = self.get_object()
        team_id = request.data.get('team_id')
        
        if not team_id:
            return Response({'error': 'team_id required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if season.teams.filter(id=team_id).exists():
            return Response({'status': 'Team already in season'})
            
        team = Team.objects.get(id=team_id)
        if team.sport != season.sport:
            return Response({'error': 'Team sport mismatch'}, status=400)
            
        season.teams.add(team)
        return Response({'status': 'Team added'})

    @action(detail=True, methods=['post'])
    def remove_team(self, request, pk=None):
        season = self.get_object()
        team_id = request.data.get('team_id')
        
        if not team_id:
            return Response({'error': 'team_id required'}, status=400)
            
        season.teams.remove(team_id)
        return Response({'status': 'Team removed'})
    
    @action(detail=True, methods=['get'])
    def standings(self, request, league_pk=None, pk=None):
        season = self.get_object()
        raw_standings = season.standings()
        
        standings_data = {item['team_id']: item for item in raw_standings}
        
        teams = season.teams.all()
        
        serializer = TeamStandingsSerializer(
            teams,
            many=True,
            context={
                'request': request,
                'standings_data': standings_data
            }
        )
        
        # Sort by standings criteria
        sorted_data = sorted(
            serializer.data,
            key=lambda x: (
                -x['standings'].get('points', 0),
                -x['standings'].get('win_percentage', 0)
            )
        )
        
        return Response(sorted_data)
        
    @action(detail=True, methods=['get'])
    def team_performance(self, request, league_pk=None, pk=None):
        """Get detailed performance metrics for teams in a season"""
        season = self.get_object()
        
        # Get completed games in this season
        from games.models import Game
        games = Game.objects.filter(
            season=season,
            status="completed"
        ).select_related('home_team', 'away_team')
        
        # Calculate team performance metrics
        teams = season.teams.all()
        team_performance = []
        
        for team in teams:
            # Get all games involving this team
            team_games = games.filter(
                Q(home_team=team) | Q(away_team=team)
            )
            
            # Calculate average points scored and conceded
            points_scored = 0
            points_conceded = 0
            
            for game in team_games:
                if game.home_team == team:
                    points_scored += game.home_team_score
                    points_conceded += game.away_team_score
                else:
                    points_scored += game.away_team_score
                    points_conceded += game.home_team_score
                    
            games_count = team_games.count()
            
            # Calculate averages
            avg_points_scored = points_scored / games_count if games_count > 0 else 0
            avg_points_conceded = points_conceded / games_count if games_count > 0 else 0
            
            # Get first and second half performance
            first_half_wins = 0
            second_half_wins = 0
            
            half_count = len(team_games) // 2
            first_half_games = list(team_games.order_by('date'))[:half_count]  # Changed from scheduled_date to date
            second_half_games = list(team_games.order_by('date'))[half_count:]  # Changed from scheduled_date to date
            
            for game in first_half_games:
                if (game.home_team == team and game.home_team_score > game.away_team_score) or \
                   (game.away_team == team and game.away_team_score > game.home_team_score):
                    first_half_wins += 1
                    
            for game in second_half_games:
                if (game.home_team == team and game.home_team_score > game.away_team_score) or \
                   (game.away_team == team and game.away_team_score > game.home_team_score):
                    second_half_wins += 1
            
            # Get win streaks
            current_streak = 0
            max_streak = 0
            
            for game in team_games.order_by('date'):  # Changed from scheduled_date to date
                is_win = (game.home_team == team and game.home_team_score > game.away_team_score) or \
                         (game.away_team == team and game.away_team_score > game.home_team_score)
                
                if is_win:
                    current_streak = current_streak + 1 if current_streak >= 0 else 1
                else:
                    current_streak = current_streak - 1 if current_streak <= 0 else -1
                
                max_streak = max(max_streak, current_streak)
            
            # Compile team performance data
            performance = {
                'team_id': team.id,
                'team_name': team.name,
                'team_name': team.slug,
                'team_logo': request.build_absolute_uri(team.logo.url) if team.logo and request else None,
                'games_played': games_count,
                'avg_points_scored': round(avg_points_scored, 2),
                'avg_points_conceded': round(avg_points_conceded, 2),
                'first_half_wins': first_half_wins,
                'second_half_wins': second_half_wins,
                'point_differential': round(avg_points_scored - avg_points_conceded, 2),
                'max_win_streak': max_streak,
                'current_streak': current_streak
            }
            
            team_performance.append(performance)
        
        # Sort by point differential
        team_performance.sort(key=lambda x: -x['point_differential'])
        
        return Response(team_performance)
        
    @action(detail=False, methods=['get'])
    def comparison(self, request, league_pk=None):
        """Compare multiple seasons in the same league"""
        league = get_object_or_404(League, pk=league_pk)
        seasons_ids = request.query_params.get('seasons', '').split(',')
        
        if not seasons_ids or not seasons_ids[0]:
            # Default to all completed seasons
            seasons = Season.objects.filter(
                league=league, 
                status='completed'
            ).order_by('-year')[:5]
        else:
            seasons = Season.objects.filter(
                league=league, 
                id__in=seasons_ids
            )
        
        comparison_data = []
        
        for season in seasons:
            # Get season standings
            standings = season.standings()
            
            # Get season games
            from games.models import Game
            games = Game.objects.filter(
                season=season,
                status="completed"
            )
            
            # Calculate average points per game
            total_points = sum(game.home_team_score + game.away_team_score for game in games)
            avg_points_per_game = total_points / games.count() if games.count() > 0 else 0
            
            # Find champion
            from brackets.models import Bracket
            champion = None
            try:
                bracket = Bracket.objects.get(season=season)
                if bracket.winner:
                    champion = bracket.winner.name
            except Bracket.DoesNotExist:
                pass
            
            # Collect data for this season
            season_data = {
                'id': season.id,
                'name': season.name,
                'year': season.year,
                'champion': champion,
                'teams_count': season.teams.count(),
                'games_count': games.count(),
                'avg_points_per_game': round(avg_points_per_game, 2),
                'top_team': standings[0]['team_name'] if standings else None,
            }
            
            comparison_data.append(season_data)
            
        return Response(comparison_data)