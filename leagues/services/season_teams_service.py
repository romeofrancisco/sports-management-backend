from django.db.models import Q, F, Sum
from games.models import Game
from sports.models import Sport

class SeasonTeamsService:
    def __init__(self, season, request=None):
        """Initialize the service with a season object.
        
        Args:
            season: Season object
            request: The HTTP request object, needed for building absolute URLs
        """
        self.season = season
        self.request = request
    
    def get_teams_with_stats(self, sort_by_standings=True):
        """Get teams in a season with extended statistics.
        
        Args:
            sort_by_standings: Whether to sort teams according to standings rules
            
        Returns:
            tuple: A tuple of (teams list, team_stats dict)
                - teams: A list of team objects, optionally ordered by standings 
                - team_stats: A dictionary of team stats by team ID
        """        # Get teams for this season
        teams = self.season.teams.prefetch_related('head_coach', 'assistant_coach', 'players').all()
        
        # Use the existing Season.standings() method to get all team statistics
        # This leverages the existing calculation logic and ensures consistency
        standings_data = self.season.standings(request=self.request)
        
        # Create a dictionary of team stats from standings
        team_stats = {}
        
        # Calculate recent form (not included in standings)
        for team in teams:
            games = Game.objects.filter(
                Q(home_team=team) | Q(away_team=team),
                season=self.season,
                status='completed'
            ).order_by('-date')
            
            # Get the last 5 games for form
            recent_games = games[:5]
            
            # Generate form string (W for win, L for loss)
            form = ""
            for game in recent_games:
                if game.home_team == team:
                    form += "W" if game.home_team_score > game.away_team_score else "L"
                else:
                    form += "W" if game.away_team_score > game.home_team_score else "L"
            
            # Find this team's standings data
            team_standing = next((item for item in standings_data if item['team_id'] == team.id), None)
            
            if team_standing:
                # Add form to the standings data
                team_standing['form'] = form
                
                # Use standings data directly for this team's stats
                team_stats[team.id] = team_standing
            else:
                # Fallback for teams that might not have standings data yet
                team_stats[team.id] = {'team_id': team.id, 'form': form}
        
        if sort_by_standings:
            # Create a dictionary mapping team_ids to their objects for quick lookup
            team_dict = {team.id: team for team in teams}
            
            # Convert standings to an ordered list of team objects
            team_id_order = [team_data['team_id'] for team_data in standings_data]
            
            # Create sorted list based on standings order
            sorted_teams = [team_dict[team_id] for team_id in team_id_order if team_id in team_dict]
            
            # Add any teams that might be in the teams queryset but not in standings
            # (This should be rare but ensures all teams are returned)
            remaining_teams = [team for team in teams if team.id not in team_id_order]
            sorted_teams.extend(remaining_teams)
            
            return sorted_teams, team_stats
        
        return teams, team_stats
