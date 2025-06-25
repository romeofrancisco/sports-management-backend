from django.db.models import Q
from games.models import Game
from datetime import datetime

class SeasonGamesService:
    def __init__(self, season):
        """Initialize the service with a season object.
        
        Args:
            season: Season object
        """
        self.season = season
    
    def get_games(self, filters=None):
        """Get games for a season with filtering options.
        
        Args:
            filters: Dictionary of filters to apply (status, team_id, date)
            
        Returns:
            QuerySet: A filtered queryset of games
        """
        # Default empty filters
        if filters is None:
            filters = {}
        
        # Get games for this season
        games = Game.objects.filter(season=self.season).select_related(
            'home_team', 'away_team', 'season'
        ).order_by('date')
        
        # Apply filters if provided
        status = filters.get('status')
        if status:
            games = games.filter(status=status)
            
        team_id = filters.get('team')
        if team_id:
            games = games.filter(Q(home_team_id=team_id) | Q(away_team_id=team_id))
            
        # Filter by date if provided (exact date match)
        date = filters.get('date')
        if date:
            try:
                # Parse the date and filter games on that specific date
                parsed_date = datetime.strptime(date, '%Y-%m-%d').date()
                games = games.filter(date=parsed_date)  # FIX: use date=parsed_date for DateField
            except ValueError:
                pass

        return games
