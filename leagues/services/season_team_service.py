from teams.models import Team

class SeasonTeamService:
    def __init__(self, season):
        """Initialize the service with a season object.
        
        Args:
            season: Season object
        """
        self.season = season
    
    def add_team(self, team_id):
        """Add a team to a season.
        
        Args:
            team_id: The ID of the team to add
            
        Returns:
            dict: A dictionary with status information
            
        Raises:
            Team.DoesNotExist: If the team does not exist
            ValueError: If the team sport doesn't match the season sport
        """
        if not team_id:
            return {'error': 'team_id required'}, 400
        
        if self.season.teams.filter(id=team_id).exists():
            return {'status': 'Team already in season'}, 200
            
        team = Team.objects.get(id=team_id)
        if team.sport != self.season.sport:
            return {'error': 'Team sport mismatch'}, 400
            
        self.season.teams.add(team)
        return {'status': 'Team added'}, 200
    
    def remove_team(self, team_id):
        """Remove a team from a season.
        
        Args:
            team_id: The ID of the team to remove
            
        Returns:
            dict: A dictionary with status information
        """
        if not team_id:
            return {'error': 'team_id required'}, 400
            
        self.season.teams.remove(team_id)
        return {'status': 'Team removed'}, 200
