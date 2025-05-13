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
        
        # Track set margin metrics
        close_sets = 0  # Sets won/lost by < 3 points
        dominant_sets = 0  # Sets won by > 10 points
        extended_sets = 0  # Sets that went beyond standard win threshold (usually 25 points in volleyball)
        
        # Track efficiency metrics
        total_set_efficiency = 0  # Percentage of points won vs total points in sets
          # Standard win threshold for volleyball is 25 points (or 15 for final set)
        # This will be used to identify extended sets
        standard_win_threshold = 25
        
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
                    
                    # Calculate margin metrics
                    score_diff = abs(team_score - opponent_score)
                    
                    # Close set - margin less than 3 points
                    if score_diff < 3:
                        close_sets += 1
                    
                    # Dominant set - team won by more than 10 points
                    if is_winner and score_diff > 10:
                        dominant_sets += 1
                    
                    # Extended set - went beyond standard win threshold
                    if team_score > standard_win_threshold or opponent_score > standard_win_threshold:
                        extended_sets += 1
                        
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
                    
                    # Calculate margin metrics
                    score_diff = abs(team_score - opponent_score)
                    
                    # Close set - margin less than 3 points
                    if score_diff < 3:
                        close_sets += 1
                    
                    # Dominant set - team won by more than 10 points
                    if is_winner and score_diff > 10:
                        dominant_sets += 1
                    
                    # Extended set - went beyond standard win threshold
                    if team_score > standard_win_threshold or opponent_score > standard_win_threshold:
                        extended_sets += 1
                        
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
                    
                    # Calculate set margin metrics
                    score_diff = abs(team_score - opponent_score)
                    
                    # Close set - margin less than 3 points
                    if score_diff < 3:
                        close_sets += 1
                    
                    # Dominant set - team won by more than 10 points
                    if is_winner and score_diff > 10:
                        dominant_sets += 1
                    
                    # Extended set - went beyond standard win threshold 
                    if team_score > standard_win_threshold or opponent_score > standard_win_threshold:
                        extended_sets += 1
                    
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
          # Get first and second half performance
        half_count = len(team_games) // 2
        first_half_games = list(team_games.order_by('date'))[:half_count]
        second_half_games = list(team_games.order_by('date'))[half_count:]
        
        first_half_wins = 0
        second_half_wins = 0
        first_half_sets_won = 0
        second_half_sets_won = 0
        
        # For set-based sports, we need to count sets won in each half of the season
        for game in first_half_games:
            # Count match wins (for backward compatibility)
            if game.winner == team:
                first_half_wins += 1
            
            # Count sets won in first half
            game_sets = GameSet.objects.filter(game=game)
            if not game_sets.exists():
                # Single set game
                if game.winner == team:
                    first_half_sets_won += 1
            else:
                # Multiple sets in game
                for game_set in game_sets:
                    if game_set.winner == team:
                        first_half_sets_won += 1
        
        for game in second_half_games:
            # Count match wins (for backward compatibility)
            if game.winner == team:
                second_half_wins += 1
                
            # Count sets won in second half
            game_sets = GameSet.objects.filter(game=game)
            if not game_sets.exists():
                # Single set game
                if game.winner == team:
                    second_half_sets_won += 1
            else:
                # Multiple sets in game
                for game_set in game_sets:
                    if game_set.winner == team:
                        second_half_sets_won += 1
        
        # Calculate streak
        current_streak = 0
        max_streak = 0
        
        for game in team_games.order_by('date'):
            is_win = game.winner == team
            
            if is_win:
                current_streak = current_streak + 1 if current_streak >= 0 else 1
            else:
                current_streak = current_streak - 1 if current_streak <= 0 else -1
            
            max_streak = max(max_streak, current_streak)        # Create the performance metrics dictionary
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
            'first_half_wins': first_half_wins,
            'second_half_wins': second_half_wins,
            'first_half_sets_won': first_half_sets_won,
            'second_half_sets_won': second_half_sets_won,
            'max_streak': max_streak,
            'current_streak': current_streak,
            'total_games': games_count,
            # Set margin metrics
            'close_games': close_sets,  # Using the UI convention of 'games' even for sets
            'blowout_wins': dominant_sets,  # Using the UI convention of 'blowout_wins' even for dominant sets
            'overtime_games': extended_sets  # Using the UI convention of 'overtime_games' even for extended sets
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
        
        # Track game margin metrics
        close_games = 0  # Games decided by < 5 points
        blowout_wins = 0  # Games won by > 15 points
        overtime_games = 0  # Games that went to overtime
        
        for game in team_games:
            # Check if game went to overtime
            if game.sport.has_period and game.current_period > game.sport.max_period:
                overtime_games += 1
                
            if game.home_team == team:
                # Team is home team
                team_score = game.home_team_score
                opponent_score = game.away_team_score
                points_scored += team_score
                points_conceded += opponent_score
                
                # Calculate margin metrics
                score_diff = abs(team_score - opponent_score)
                
                # Close game
                if score_diff < 5:
                    close_games += 1
                
                # Blowout win (only if team won)
                if team_score > opponent_score and score_diff > 15:
                    blowout_wins += 1
            else:
                # Team is away team
                team_score = game.away_team_score
                opponent_score = game.home_team_score
                points_scored += team_score
                points_conceded += opponent_score
                
                # Calculate margin metrics
                score_diff = abs(team_score - opponent_score)
                
                # Close game
                if score_diff < 5:
                    close_games += 1
                
                # Blowout win (only if team won)
                if team_score > opponent_score and score_diff > 15:
                    blowout_wins += 1
                
        # Calculate averages
        avg_points_scored = points_scored / games_count if games_count > 0 else 0
        avg_points_conceded = points_conceded / games_count if games_count > 0 else 0
        
        # Get first and second half performance
        half_count = len(team_games) // 2
        first_half_games = list(team_games.order_by('date'))[:half_count]
        second_half_games = list(team_games.order_by('date'))[half_count:]
        
        first_half_wins = 0
        second_half_wins = 0
        
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
            'avg_points_scored': round(avg_points_scored, 2),
            'avg_points_conceded': round(avg_points_conceded, 2),
            'first_half_wins': first_half_wins,
            'second_half_wins': second_half_wins,
            'point_differential': round(avg_points_scored - avg_points_conceded, 2),
            'max_streak': max_streak,
            'current_streak': current_streak,
            'total_games': games_count,
            # Game margin metrics
            'close_games': close_games,
            'blowout_wins': blowout_wins,
            'overtime_games': overtime_games
        }
        
        return performance
