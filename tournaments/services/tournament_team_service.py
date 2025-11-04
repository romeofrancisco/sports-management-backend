from django.db.models import Q, F, Sum
from games.models import Game, GameSet


class TournamentTeamService:
    def __init__(self, tournament, team, request=None):
        """Initialize the service with a tournament and team object.
        
        Args:
            tournament: Tournament object
            team: Team object
            request: The HTTP request object, needed for building absolute URLs
        """
        self.tournament = tournament
        self.team = team
        self.sport = tournament.sport
        self.request = request
        self.is_set_based = self.sport.scoring_type == 'sets'
    
    def get_team_statistics(self):
        """Get comprehensive statistics for a team in the tournament.
        
        Returns:
            dict: A dictionary containing team statistics
        """
        # Get all games for this team in the tournament
        all_games = Game.objects.filter(
            Q(home_team=self.team) | Q(away_team=self.team),
            tournament=self.tournament
        )
        
        completed_games = all_games.filter(status="completed")
        
        # Basic stats
        total_games = completed_games.count()
        
        if total_games == 0:
            return {
                "team_id": self.team.id,
                "team_name": self.team.name,
                "total_games": 0,
                "message": "No completed games found"
            }
        
        # Calculate wins, losses, ties
        wins = completed_games.filter(
            Q(home_team=self.team, home_team_score__gt=F('away_team_score')) |
            Q(away_team=self.team, away_team_score__gt=F('home_team_score'))
        ).count()
        
        losses = completed_games.filter(
            Q(home_team=self.team, home_team_score__lt=F('away_team_score')) |
            Q(away_team=self.team, away_team_score__lt=F('home_team_score'))
        ).count()
        
        ties = 0
        if self.sport.has_tie:
            ties = completed_games.filter(
                Q(home_team=self.team, home_team_score=F('away_team_score')) |
                Q(away_team=self.team, away_team_score=F('home_team_score'))
            ).count()
        
        win_percentage = round((wins / total_games) * 100, 1) if total_games > 0 else 0
        
        stats = {
            "team_id": self.team.id,
            "team_name": self.team.name,
            "team_logo": self.request.build_absolute_uri(self.team.logo.url) if self.team.logo and self.request else None,
            "total_games": total_games,
            "wins": wins,
            "losses": losses,
            "win_percentage": win_percentage,
        }
        
        if self.sport.has_tie:
            stats["ties"] = ties
        
        # Add sport-specific stats
        if self.is_set_based:
            stats.update(self._get_set_based_stats(completed_games))
        else:
            stats.update(self._get_point_based_stats(completed_games))
        
        return stats
    
    def _get_set_based_stats(self, completed_games):
        """Get set-based statistics for the team.
        
        Returns:
            dict: Set-based statistics
        """
        sets_won = 0
        sets_lost = 0
        total_points_scored = 0
        total_points_conceded = 0
        
        for game in completed_games:
            game_sets = GameSet.objects.filter(game=game)
            
            if game.home_team == self.team:
                sets_won += GameSet.objects.filter(game=game, winner=self.team).count()
                sets_lost += GameSet.objects.filter(game=game, winner=game.away_team).count()
                
                for game_set in game_sets:
                    total_points_scored += game_set.home_team_score
                    total_points_conceded += game_set.away_team_score
            else:
                sets_won += GameSet.objects.filter(game=game, winner=self.team).count()
                sets_lost += GameSet.objects.filter(game=game, winner=game.home_team).count()
                
                for game_set in game_sets:
                    total_points_scored += game_set.away_team_score
                    total_points_conceded += game_set.home_team_score
        
        sets_played = sets_won + sets_lost
        set_win_percentage = round((sets_won / sets_played) * 100, 1) if sets_played > 0 else 0
        avg_points_per_set = round(total_points_scored / sets_played, 1) if sets_played > 0 else 0
        
        return {
            "sets_won": sets_won,
            "sets_lost": sets_lost,
            "sets_played": sets_played,
            "set_win_percentage": set_win_percentage,
            "avg_points_per_set": avg_points_per_set,
            "total_points_scored": total_points_scored,
            "total_points_conceded": total_points_conceded,
        }
    
    def _get_point_based_stats(self, completed_games):
        """Get point-based statistics for the team.
        
        Returns:
            dict: Point-based statistics
        """
        total_points_scored = 0
        total_points_conceded = 0
        
        for game in completed_games:
            if game.home_team == self.team:
                total_points_scored += game.home_team_score
                total_points_conceded += game.away_team_score
            else:
                total_points_scored += game.away_team_score
                total_points_conceded += game.home_team_score
        
        games_count = completed_games.count()
        avg_points_scored = round(total_points_scored / games_count, 1) if games_count > 0 else 0
        avg_points_conceded = round(total_points_conceded / games_count, 1) if games_count > 0 else 0
        point_differential = total_points_scored - total_points_conceded
        
        return {
            "total_points_scored": total_points_scored,
            "total_points_conceded": total_points_conceded,
            "avg_points_scored": avg_points_scored,
            "avg_points_conceded": avg_points_conceded,
            "point_differential": point_differential,
        }
    
    def get_team_games(self):
        """Get all games for the team in the tournament.
        
        Returns:
            QuerySet: Games involving the team
        """
        return Game.objects.filter(
            Q(home_team=self.team) | Q(away_team=self.team),
            tournament=self.tournament
        ).order_by('-game_date')
