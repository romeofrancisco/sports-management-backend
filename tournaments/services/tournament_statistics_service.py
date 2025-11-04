from django.db.models import Count, Avg, F, Q
from sports.models import Sport
from brackets.models import Bracket
from games.models import Game, GameSet


class TournamentStatisticsService:
    def __init__(self, tournament, request=None):
        """Initialize the service with a tournament object.
        
        Args:
            tournament: Tournament object
            request: The HTTP request object, needed for building absolute URLs
        """
        self.tournament = tournament
        self.sport = tournament.sport
        self.request = request
        self.is_set_based = self.sport.scoring_type == Sport.SCORING_TYPES.SETS
        
    def get_statistics(self):
        """Get comprehensive tournament statistics.
        
        Returns:
            dict: A dictionary containing tournament statistics
        """
        from tournaments.serializers import TournamentSerializer
        
        # Count teams and games
        teams_count = self.tournament.teams.count()
        
        # Get all completed games in the tournament
        all_games = Game.objects.filter(
            tournament=self.tournament,
            status="completed"
        )
        games_count = all_games.count()
        games_played = games_count
        
        statistics = {
            "teams_count": teams_count,
            "games_count": games_count,
            "games_played": games_played,
            "status": self.tournament.status,
            "start_date": self.tournament.start_date,
            "end_date": self.tournament.end_date,
        }
        
        return statistics
    
    def get_comprehensive_stats(self):
        """Get detailed comprehensive statistics for the entire tournament.
        
        Returns:
            dict: A dictionary containing detailed tournament statistics
        """
        # Get all completed games in the tournament
        all_games = Game.objects.filter(
            tournament=self.tournament,
            status="completed"
        ).select_related('home_team', 'away_team')
        
        # Calculate total games count
        total_games = all_games.count()
        if total_games == 0:
            return {
                "detail": "No completed games found in this tournament."
            }
            
        # Get all teams that participated
        all_teams = self.tournament.teams.all()
        
        if self.is_set_based:
            return self._get_set_based_comprehensive_stats(all_games, all_teams, total_games)
        else:
            return self._get_point_based_comprehensive_stats(all_games, all_teams, total_games)
    
    def _get_set_based_comprehensive_stats(self, all_games, all_teams, total_games):
        """Get comprehensive statistics for set-based sports.
        
        Returns:
            dict: A dictionary containing set-based statistics
        """
        # Set-based sport statistics (volleyball, tennis, etc.)
        total_sets_played = GameSet.objects.filter(game__tournament=self.tournament).count()
        total_matches = total_games
        avg_sets_per_match = total_sets_played / total_matches if total_matches > 0 else 0
        
        # Set score distribution
        set_scores = GameSet.objects.filter(
            game__tournament=self.tournament,
            home_team_score__gt=0,
            away_team_score__gt=0
        ).values_list('home_team_score', 'away_team_score')
        
        # Count deuce sets (close games)
        deuce_sets = sum(1 for h, a in set_scores if abs(h - a) <= 2)
        
        # Calculate average points per set
        if total_sets_played > 0:
            total_points = sum(h + a for h, a in set_scores)
            avg_points_per_set = total_points / total_sets_played
        else:
            avg_points_per_set = 0
        
        return {
            "total_games": total_games,
            "total_sets_played": total_sets_played,
            "avg_sets_per_match": round(avg_sets_per_match, 2),
            "deuce_sets": deuce_sets,
            "avg_points_per_set": round(avg_points_per_set, 1),
            "sport_type": "set-based"
        }
    
    def _get_point_based_comprehensive_stats(self, all_games, all_teams, total_games):
        """Get comprehensive statistics for point-based sports.
        
        Returns:
            dict: A dictionary containing point-based statistics
        """
        # Calculate total points scored
        total_home_points = sum(game.home_team_score for game in all_games)
        total_away_points = sum(game.away_team_score for game in all_games)
        total_points = total_home_points + total_away_points
        
        # Calculate averages
        avg_total_points_per_game = total_points / total_games if total_games > 0 else 0
        avg_home_points = total_home_points / total_games if total_games > 0 else 0
        avg_away_points = total_away_points / total_games if total_games > 0 else 0
        
        # Find highest and lowest scoring games
        highest_scoring_game = max(all_games, key=lambda g: g.home_team_score + g.away_team_score, default=None)
        lowest_scoring_game = min(all_games, key=lambda g: g.home_team_score + g.away_team_score, default=None)
        
        # Count close games (within 5 points)
        close_games = sum(1 for game in all_games if abs(game.home_team_score - game.away_team_score) <= 5)
        
        # Count blowouts (difference > 20 points)
        blowouts = sum(1 for game in all_games if abs(game.home_team_score - game.away_team_score) > 20)
        
        stats = {
            "total_games": total_games,
            "total_points_scored": total_points,
            "avg_points_per_game": round(avg_total_points_per_game, 1),
            "avg_home_points": round(avg_home_points, 1),
            "avg_away_points": round(avg_away_points, 1),
            "close_games": close_games,
            "blowouts": blowouts,
            "sport_type": "point-based"
        }
        
        if highest_scoring_game:
            stats["highest_scoring_game"] = {
                "id": highest_scoring_game.id,
                "home_team": highest_scoring_game.home_team.name,
                "away_team": highest_scoring_game.away_team.name,
                "score": f"{highest_scoring_game.home_team_score} - {highest_scoring_game.away_team_score}",
                "total_points": highest_scoring_game.home_team_score + highest_scoring_game.away_team_score
            }
        
        if lowest_scoring_game:
            stats["lowest_scoring_game"] = {
                "id": lowest_scoring_game.id,
                "home_team": lowest_scoring_game.home_team.name,
                "away_team": lowest_scoring_game.away_team.name,
                "score": f"{lowest_scoring_game.home_team_score} - {lowest_scoring_game.away_team_score}",
                "total_points": lowest_scoring_game.home_team_score + lowest_scoring_game.away_team_score
            }
        
        return stats
    
    def get_team_form(self, last_n_games=5):
        """Get recent form for teams in the tournament.
        
        Args:
            last_n_games: Number of recent games to consider for form
            
        Returns:
            list: List of teams with their recent form and statistics, sorted by standings
        """
        from brackets.models import Bracket
        
        # Get the proper standings from the tournament model
        standings = self.tournament.standings(request=self.request)
        
        # Check if tournament has a bracket and get elimination type
        bracket = self.tournament.get_bracket
        is_round_robin = bracket and bracket.elimination_type == Bracket.ELIMINATION_TYPES.ROUND_ROBIN
        
        team_form_data = []
        
        # Use standings order (already properly sorted with all tiebreakers)
        for standing in standings:
            team_id = standing['team_id']
            
            # Get the team object
            team = self.tournament.teams.filter(id=team_id).first()
            if not team:
                continue
            
            # Get last N games for this team
            recent_games = Game.objects.filter(
                Q(home_team=team) | Q(away_team=team),
                tournament=self.tournament,
                status="completed"
            ).order_by('-date')[:last_n_games]
            
            # Build recent form array
            form = []
            for game in reversed(recent_games):
                if game.home_team == team:
                    if game.home_team_score > game.away_team_score:
                        form.append("W")
                    elif game.home_team_score < game.away_team_score:
                        form.append("L")
                    else:
                        form.append("D")
                else:
                    if game.away_team_score > game.home_team_score:
                        form.append("W")
                    elif game.away_team_score < game.home_team_score:
                        form.append("L")
                    else:
                        form.append("D")
            
            # Use data from standings and add form information
            team_form_data.append({
                "team_id": standing['team_id'],
                "team_name": standing['team_name'],
                "team_logo": standing.get('team_logo'),
                "form": form,
                "recent_games_count": len(form),
                "wins": standing['wins'],
                "losses": standing['losses'],
                "draws": standing.get('ties', 0),  # Note: standings uses 'ties' not 'draws'
                "win_ratio": standing.get('win_percentage', 0),  # standings uses 'win_percentage'
                "match_points": standing.get('points', 0) if is_round_robin else 0,
                "point_differential": standing.get('point_differential', 0),
            })
        
        return team_form_data
