from django.shortcuts import get_object_or_404
from games.models import Game
from brackets.models import Bracket
from ..models import Season, League

class SeasonComparisonService:
    def __init__(self, league):
        """Initialize the service with a league object.
        
        Args:
            league: League object
        """
        self.league = league
    
    def get_comparison_data(self, seasons_ids=None):
        """Get comparison data for multiple seasons.
        
        Args:
            seasons_ids: List of season IDs to compare
            
        Returns:
            list: A list of dictionaries containing comparison data for each season
        """
        if not seasons_ids or not seasons_ids[0]:
            # Default to all completed seasons
            seasons = Season.objects.filter(
                league=self.league, 
                status='completed'
            ).order_by('-year')[:5]
        else:
            seasons = Season.objects.filter(
                league=self.league, 
                id__in=seasons_ids
            )
        
        comparison_data = []
        
        for season in seasons:
            # Get season standings
            standings = season.standings()
            
            # Get season games
            games = Game.objects.filter(
                season=season,
                status="completed"
            )
            
            # Calculate average points per game
            total_points = sum(game.home_team_score + game.away_team_score for game in games)
            avg_points_per_game = total_points / games.count() if games.count() > 0 else 0
            
            # Find champion
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
        
        return comparison_data
