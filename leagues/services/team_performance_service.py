from django.db.models import Q, F, Func
from sports.models import Sport
from teams.models import Team
from games.models import Game, GameSet

class TeamPerformanceService:
    def __init__(self, season, request=None):
        """Initialize the service with a season object.
        
        Args:
            season: Season object
            request: The HTTP request object, needed for building absolute URLs
        """
        self.season = season
        self.sport = season.league.sport
        self.is_set_based = self.sport.scoring_type == Sport.SCORING_TYPES.SETS
        self.request = request
        
        # Get completed games in this season
        self.games = Game.objects.filter(
            season=season,
            status="completed"
        ).select_related('home_team', 'away_team')
    
    def get_team_performance(self):
        """Calculate team performance metrics for all teams in a season.
        
        Returns:
            list: List of dictionaries containing team performance data
        """
        teams = self.season.teams.all()
        team_performance = []
        
        for team in teams:
            # Get all games involving this team
            team_games = self.games.filter(
                Q(home_team=team) | Q(away_team=team)
            )
            
            games_count = team_games.count()
            
            if self.is_set_based:
                performance = self._calculate_set_based_performance(team, team_games, games_count)
            else:
                performance = self._calculate_point_based_performance(team, team_games, games_count)
            
            team_performance.append(performance)
        
        # Sort by appropriate metric
        if self.is_set_based:
            # Sort by set win percentage for set-based sports
            team_performance.sort(key=lambda x: (-x['match_win_percentage'], -x['set_win_percentage']))
        else:
            # Sort by point differential for point-based sports
            team_performance.sort(key=lambda x: -x['point_differential'])
        
        return team_performance
    
    def _calculate_set_based_performance(self, team, team_games, games_count):
        """Calculate performance metrics for set-based sports like volleyball or tennis.
        
        Args:
            team: Team object
            team_games: QuerySet of games involving the team
            games_count: Number of games played by the team
            
        Returns:
            dict: Dictionary containing team performance data for set-based sports
        """
        # Get sets played by this team
        total_sets_played = 0
        sets_won = 0
        total_points_scored = 0
        total_points_conceded = 0
        
        # Track efficiency metrics
        total_set_efficiency = 0  # Percentage of points won vs total points in sets
        
        for game in team_games:
            # Get all sets for this game
            game_sets = GameSet.objects.filter(game=game)
            
            # If no game sets exist but the game has a final score, treat the game itself as a single set
            if not game_sets.exists():
                total_sets_played += 1
                
                if game.home_team == team:
                    # Team is home team
                    team_score = game.home_team_score
                    opponent_score = game.away_team_score
                    total_points_scored += team_score
                    total_points_conceded += opponent_score
                    
                    is_winner = game.winner == team
                    if is_winner:
                        sets_won += 1
                        
                    # Calculate set efficiency for this single-set game
                    total_points = team_score + opponent_score
                    if total_points > 0:
                        total_set_efficiency += (team_score / total_points) * 100
                else:  # Away team
                    # Team is away team
                    team_score = game.away_team_score
                    opponent_score = game.home_team_score
                    total_points_scored += team_score
                    total_points_conceded += opponent_score
                    
                    is_winner = game.winner == team
                    if is_winner:
                        sets_won += 1
                        
                    # Calculate set efficiency for this single-set game
                    total_points = team_score + opponent_score
                    if total_points > 0:
                        total_set_efficiency += (team_score / total_points) * 100
            else:
                # Process all individual sets
                for game_set in game_sets:
                    if game.home_team == team:
                        # Team is home team
                        team_score = game_set.home_team_score
                        opponent_score = game_set.away_team_score
                        total_points_scored += team_score
                        total_points_conceded += opponent_score
                        is_winner = game_set.winner == team
                        if is_winner:
                            sets_won += 1
                    else:  # Away team
                        # Team is away team 
                        team_score = game_set.away_team_score
                        opponent_score = game_set.home_team_score
                        total_points_scored += team_score
                        total_points_conceded += opponent_score
                        is_winner = game_set.winner == team
                        if is_winner:
                            sets_won += 1
                    
                    total_sets_played += 1
                    
                    # Calculate set efficiency (% of total points won)
                    points_in_set = team_score + opponent_score
                    if points_in_set > 0:
                        total_set_efficiency += (team_score / points_in_set) * 100
        
        # Calculate averages
        avg_set_efficiency = round(total_set_efficiency / total_sets_played, 2) if total_sets_played > 0 else 0
        set_win_percentage = round(sets_won / total_sets_played * 100, 2) if total_sets_played > 0 else 0
        points_ratio = round(total_points_scored / total_points_conceded, 3) if total_points_conceded > 0 else 0
        
        # Calculate exact points per set values - explicit calculations for frontend
        points_per_set = round(total_points_scored / total_sets_played, 1) if total_sets_played > 0 else 0
        points_against_per_set = round(total_points_conceded / total_sets_played, 1) if total_sets_played > 0 else 0
        
        # Get match wins/losses for set-based sports
        wins = 0
        for game in team_games:
            if game.winner == team:
                wins += 1
        
        # Calculate match win percentage
        match_win_percentage = round((wins / games_count) * 100, 2) if games_count > 0 else 0
        
        # Calculate streak
        current_streak = 0
        max_streak = 0
        
        for game in team_games.order_by('date'):
            is_win = game.winner == team
            
            if is_win:
                current_streak = current_streak + 1 if current_streak >= 0 else 1
            else:
                current_streak = current_streak - 1 if current_streak <= 0 else -1
            
            max_streak = max(max_streak, current_streak)
        
        # Create the performance metrics dictionary
        performance = {
            'team_id': team.id,
            'team_name': team.name,
            'team_slug': team.slug,
            'team_color': team.color,
            'team_logo': self.request.build_absolute_uri(team.logo.url) if team.logo and self.request else None,
            'matches_played': games_count,
            'matches_won': wins,
            'matches_lost': games_count - wins,
            'match_win_percentage': match_win_percentage,
            'sets_played': total_sets_played,
            'sets_won': sets_won,
            'sets_lost': total_sets_played - sets_won,
            'set_win_percentage': set_win_percentage,
            'points_ratio': points_ratio,
            'set_efficiency': avg_set_efficiency,
            'total_points_scored': total_points_scored,
            'total_points_conceded': total_points_conceded,
            'points_per_set': points_per_set,
            'points_against_per_set': points_against_per_set,
            'max_streak': max_streak,
            'current_streak': current_streak,
            'total_games': games_count,
        }
        
        return performance
    
    def _calculate_point_based_performance(self, team, team_games, games_count):
        """Calculate performance metrics for point-based sports like basketball, football, etc.
        
        Args:
            team: Team object
            team_games: QuerySet of games involving the team
            games_count: Number of games played by the team
            
        Returns:
            dict: Dictionary containing team performance data for point-based sports
        """
        points_scored = 0
        points_conceded = 0
        wins = 0
        
        for game in team_games:
            if game.home_team == team:
                # Team is home team
                team_score = game.home_team_score
                opponent_score = game.away_team_score
                points_scored += team_score
                points_conceded += opponent_score
                
                # Check if team won
                if team_score > opponent_score:
                    wins += 1
            else:
                # Team is away team
                team_score = game.away_team_score
                opponent_score = game.home_team_score
                points_scored += team_score
                points_conceded += opponent_score
                
                # Check if team won
                if team_score > opponent_score:
                    wins += 1
        
        # Calculate averages
        avg_points_scored = points_scored / games_count if games_count > 0 else 0
        avg_points_conceded = points_conceded / games_count if games_count > 0 else 0
        
        # Calculate win percentage
        win_percentage = round((wins / games_count) * 100, 2) if games_count > 0 else 0
        
        # Get win streaks
        current_streak = 0
        max_streak = 0
        
        for game in team_games.order_by('date'):
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
            'team_slug': team.slug,
            'team_color': team.color,
            'team_logo': self.request.build_absolute_uri(team.logo.url) if team.logo and self.request else None,
            'games_played': games_count,
            'matches_won': wins,
            'matches_lost': games_count - wins,
            'win_percentage': win_percentage,
            'avg_points_scored': round(avg_points_scored, 2),
            'avg_points_conceded': round(avg_points_conceded, 2),
            'point_differential': round(avg_points_scored - avg_points_conceded, 2),
            'max_streak': max_streak,
            'current_streak': current_streak,
            'total_games': games_count,
        }
        
        return performance
