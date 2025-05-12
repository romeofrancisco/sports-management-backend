from django.db.models import Q
from games.models import Game
from teams.models import Team

class TeamFormService:
    def __init__(self, season):
        """Initialize the service with a season object.
        
        Args:
            season: Season object
        """
        self.season = season
    
    def get_team_form(self):
        """Get the recent form for teams in a season.
        
        Returns:
            tuple: (raw_standings, form_results)
        """
        # Get all teams in this season based on standings
        raw_standings = self.season.standings()
        team_ids = [team['team_id'] for team in raw_standings]
        
        # Get all teams
        teams = Team.objects.filter(id__in=team_ids)
        
        # Get recent games for each team (last 5)
        results = {}
        
        for team in teams:
            recent_games = Game.objects.filter(
                Q(home_team=team) | Q(away_team=team),
                season=self.season,
                status="completed"
            ).order_by('-date')[:5]
            
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
                    'date': game.date.strftime("%Y-%m-%d")
                })
            
            results[team.id] = team_results
        
        return raw_standings, results
