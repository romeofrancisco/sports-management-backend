from django.db.models import Count, Avg, F, Q, Func
from sports.models import Sport
from brackets.models import Bracket
from games.models import Game, GameSet

class LeagueStatisticsService:
    def __init__(self, league, request=None):
        """Initialize the service with a league object.
        
        Args:
            league: League object
            request: The HTTP request object, needed for building absolute URLs
        """
        self.league = league
        self.sport = league.sport
        self.request = request
        self.is_set_based = self.sport.scoring_type == Sport.SCORING_TYPES.SETS
        
    def get_statistics(self):
        """Get comprehensive league statistics for the dashboard.
        
        Returns:
            dict: A dictionary containing league statistics
        """
        # Count teams, seasons, games
        teams_count = self.league.seasons.aggregate(
            total_teams=Count('teams', distinct=True)
        )['total_teams']
        
        seasons_count = self.league.seasons.count()
        active_seasons = self.league.seasons.filter(status__in=["ongoing", "upcoming"]).count()
        
        # Get all completed games in the league
        all_games = Game.objects.filter(
            season__league=self.league,
            status="completed"
        )
        games_count = all_games.count()
        
        # Get current season if any
        from leagues.serializers import SeasonSerializer
        current_season = self.league.seasons.filter(status="ongoing").order_by("-start_date").first()
        current_season_data = SeasonSerializer(current_season, context={"request": self.request}).data if current_season else None
        
        statistics = {
            "teams_count": teams_count,
            "seasons_count": seasons_count,
            "active_seasons": active_seasons,
            "games_count": games_count,
            "current_season": current_season_data,
        }
        
        return statistics
    
    def get_comprehensive_stats(self):
        """Get detailed comprehensive statistics for the entire league.
        
        Returns:
            dict: A dictionary containing detailed league statistics
        """
        # Get all completed games in the league across all seasons
        all_games = Game.objects.filter(
            season__league=self.league,
            status="completed"
        ).select_related('home_team', 'away_team', 'season')
        
        # Calculate total games count
        total_games = all_games.count()
        if (total_games == 0):
            return {
                "detail": "No completed games found in this league."
            }
            
        # Get all teams that participated in any season
        all_teams = set()
        for season in self.league.seasons.all():
            all_teams.update(season.teams.all())
        
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
        total_sets_played = GameSet.objects.filter(game__season__league=self.league).count()
        total_matches = total_games
        avg_sets_per_match = total_sets_played / total_matches if total_matches > 0 else 0
        
        # Set score distribution
        set_scores = GameSet.objects.filter(
            game__season__league=self.league,
            home_team_score__gt=0,  # Ensure completed sets
            away_team_score__gt=0
        ).values('home_team_score', 'away_team_score')
        
        # Most common score patterns
        score_patterns = {}
        for s in set_scores:
            pattern = f"{s['home_team_score']}-{s['away_team_score']}"
            if pattern in score_patterns:
                score_patterns[pattern] += 1
            else:
                score_patterns[pattern] = 1
        
        # Sort patterns by frequency
        common_scores = [
            {"pattern": k, "count": v} 
            for k, v in sorted(score_patterns.items(), key=lambda x: -x[1])
        ][:10]  # Top 10 score patterns
        
        # Calculate total points across all sets
        total_points = sum(s['home_team_score'] + s['away_team_score'] for s in set_scores)
        avg_points_per_set = total_points / total_sets_played if total_sets_played > 0 else 0
        
        # Calculate league-wide stats for all teams
        team_stats = self._calculate_set_based_team_stats(all_teams)
        
        # Sort teams by match win percentage, then by set win percentage
        sorted_teams = sorted(
            team_stats.values(), 
            key=lambda x: (-x['match_win_percentage'], -x['sets_win_percentage'])
        )
        
        # Prepare championship data - which teams won brackets
        champions = Bracket.objects.filter(
            season__league=self.league,
            winner__isnull=False
        ).values('season__year', 'winner__name', 'winner__id').order_by('-season__year')
        
        # Compile response
        response = {
            "league_id": self.league.id,
            "league_name": self.league.name,
            "sport": self.sport.name,
            "scoring_type": self.sport.scoring_type,
            "total_matches": total_matches,
            "total_sets": total_sets_played,
            "avg_sets_per_match": round(avg_sets_per_match, 2),
            "avg_points_per_set": round(avg_points_per_set, 2),
            "common_set_scores": common_scores,
            "teams": sorted_teams,
            "champions": list(champions),
            "seasons_count": self.league.seasons.count(),
            "completed_seasons": self.league.seasons.filter(status="completed").count()
        }
        
        return response
    
    def _calculate_set_based_team_stats(self, all_teams):
        """Calculate statistics for teams in set-based sports.
        
        Returns:
            dict: A dictionary mapping team IDs to team statistics
        """
        team_stats = {}
        
        for team in all_teams:
            team_matches = Game.objects.filter(
                Q(home_team=team) | Q(away_team=team),
                season__league=self.league,
                status="completed"
            )
            
            matches_won = team_matches.filter(winner_team=team).count()
            matches_played = team_matches.count()
            
            # Get sets statistics
            sets_played = GameSet.objects.filter(
                Q(game__home_team=team) | Q(game__away_team=team),
                game__season__league=self.league
            )
            
            # Note: GameSet has winner field, not winner_team
            sets_won = sets_played.filter(winner=team).count()
            
            # Calculate sets won percentage
            sets_win_percentage = (sets_won / sets_played.count()) * 100 if sets_played.count() > 0 else 0
            
            # Calculate points statistics across all sets
            total_points_scored = 0
            total_points_conceded = 0
            
            for game_set in sets_played:
                if game_set.game.home_team == team:
                    total_points_scored += game_set.home_team_score
                    total_points_conceded += game_set.away_team_score
                else:
                    total_points_scored += game_set.away_team_score
                    total_points_conceded += game_set.home_team_score
            
            # Calculate points per set
            points_per_set = total_points_scored / sets_played.count() if sets_played.count() > 0 else 0
            points_conceded_per_set = total_points_conceded / sets_played.count() if sets_played.count() > 0 else 0
            
            team_stats[team.id] = {
                "team_id": team.id,
                "team_name": team.name,
                "matches_played": matches_played,
                "matches_won": matches_won,
                "matches_lost": matches_played - matches_won,
                "match_win_percentage": (matches_won / matches_played) * 100 if matches_played > 0 else 0,
                "sets_played": sets_played.count(),
                "sets_won": sets_won,
                "sets_lost": sets_played.count() - sets_won,
                "sets_win_percentage": sets_win_percentage,
                "points_per_set": round(points_per_set, 2),
                "points_conceded_per_set": round(points_conceded_per_set, 2),
                "point_efficiency": round((total_points_scored / (total_points_scored + total_points_conceded)) * 100, 2) 
                if (total_points_scored + total_points_conceded) > 0 else 0
            }
            
        return team_stats
    
    def _get_point_based_comprehensive_stats(self, all_games, all_teams, total_games):
        """Get comprehensive statistics for point-based sports.
        
        Returns:
            dict: A dictionary containing point-based statistics
        """
        # Point-based sport statistics (basketball, football, etc.)
        total_points = sum(game.home_team_score + game.away_team_score for game in all_games)
        avg_points_per_game = total_points / total_games if total_games > 0 else 0
        
        # Get highest scoring games
        highest_scoring_games = all_games.annotate(
            total_score=F('home_team_score') + F('away_team_score')
        ).order_by('-total_score')[:5]
        
        # Get biggest margin games
        biggest_margin_games = all_games.annotate(
            margin=Func(F('home_team_score') - F('away_team_score'), function='ABS')
        ).order_by('-margin')[:5]
        
        # Calculate league-wide stats for all teams
        team_stats = self._calculate_point_based_team_stats(all_teams)
        
        # Sort teams by win percentage, then by point differential
        sorted_teams = sorted(
            team_stats.values(), 
            key=lambda x: (-x['win_percentage'], -x['point_differential'])
        )
        
        # Prepare championship data - which teams won brackets
        champions = Bracket.objects.filter(
            season__league=self.league,
            winner__isnull=False
        ).values('season__year', 'winner__name', 'winner__id').order_by('-season__year')
        
        # Prepare highest scoring games data
        high_scoring_games = []
        for game in highest_scoring_games:
            high_scoring_games.append({
                'game_id': game.id,
                'date': game.date.strftime('%Y-%m-%d'),
                'home_team': game.home_team.name,
                'away_team': game.away_team.name,
                'home_score': game.home_team_score,
                'away_score': game.away_team_score,
                'total_score': game.home_team_score + game.away_team_score,
                'season': game.season.name,
                'season_year': game.season.year
            })
        
        # Prepare biggest margin games data
        margin_games = []
        for game in biggest_margin_games:
            margin_games.append({
                'game_id': game.id,
                'date': game.date.strftime('%Y-%m-%d'),
                'home_team': game.home_team.name,
                'away_team': game.away_team.name,
                'home_score': game.home_team_score,
                'away_score': game.away_team_score, 
                'margin': abs(game.home_team_score - game.away_team_score),
                'winner': game.winner_team.name if game.winner_team else None,
                'season': game.season.name,
                'season_year': game.season.year
            })
        
        # Compile response
        response = {
            "league_id": self.league.id,
            "league_name": self.league.name,
            "sport": self.sport.name,
            "scoring_type": self.sport.scoring_type,
            "total_games": total_games,
            "avg_points_per_game": round(avg_points_per_game, 2),
            "highest_scoring_games": high_scoring_games,
            "biggest_margin_games": margin_games,
            "teams": sorted_teams,
            "champions": list(champions),
            "seasons_count": self.league.seasons.count(),
            "completed_seasons": self.league.seasons.filter(status="completed").count()
        }
        
        return response
    
    def _calculate_point_based_team_stats(self, all_teams):
        """Calculate statistics for teams in point-based sports.
        
        Returns:
            dict: A dictionary mapping team IDs to team statistics
        """
        team_stats = {}
        
        for team in all_teams:
            team_games = Game.objects.filter(
                Q(home_team=team) | Q(away_team=team),
                season__league=self.league,
                status="completed"
            )
            
            games_won = team_games.filter(winner_team=team).count()
            games_played = team_games.count()
            
            # Calculate home vs away records
            home_games = team_games.filter(home_team=team)
            away_games = team_games.filter(away_team=team)
            
            home_wins = home_games.filter(winner_team=team).count()
            away_wins = away_games.filter(winner_team=team).count()
            
            # Calculate points statistics
            total_points_scored = 0
            total_points_conceded = 0
            
            for game in team_games:
                if game.home_team == team:
                    total_points_scored += game.home_team_score
                    total_points_conceded += game.away_team_score
                else:
                    total_points_scored += game.away_team_score
                    total_points_conceded += game.home_team_score
            
            # Calculate points per game
            points_per_game = total_points_scored / games_played if games_played > 0 else 0
            points_conceded_per_game = total_points_conceded / games_played if games_played > 0 else 0
            
            # Calculate point differential
            point_differential = points_per_game - points_conceded_per_game
            
            # Calculate winning streaks
            longest_win_streak = 0
            current_streak = 0
            last_win = None
            
            for game in team_games.order_by('date'):
                is_win = game.winner_team == team
                
                if is_win:
                    if last_win is False or last_win is None:
                        current_streak = 1
                    else:
                        current_streak += 1
                    
                    longest_win_streak = max(longest_win_streak, current_streak)
                else:
                    current_streak = 0
                
                last_win = is_win
            
            team_stats[team.id] = {
                "team_id": team.id,
                "team_name": team.name,
                "games_played": games_played,
                "games_won": games_won,
                "games_lost": games_played - games_won,
                "win_percentage": (games_won / games_played) * 100 if games_played > 0 else 0,
                "home_games_played": home_games.count(),
                "home_wins": home_wins,
                "home_losses": home_games.count() - home_wins,
                "away_games_played": away_games.count(),
                "away_wins": away_wins,
                "away_losses": away_games.count() - away_wins,
                "points_per_game": round(points_per_game, 2),
                "points_conceded_per_game": round(points_conceded_per_game, 2),
                "point_differential": round(point_differential, 2),
                "longest_win_streak": longest_win_streak
            }
            
        return team_stats
    
    def get_team_form(self):
        """Get the recent form for top teams in the league.
        
        Returns:
            dict: A dictionary containing team standings and form data
        """
        # Get all teams based on standings
        teams_data = self.league.standings(request=self.request)
        team_ids = [team['team_id'] for team in teams_data]
        
        # Get all teams
        from teams.models import Team
        teams = Team.objects.filter(id__in=team_ids)
        
        # Get recent games for each team (last 5)
        results = {}
        
        for team in teams:
            recent_games = Game.objects.filter(
                Q(home_team=team) | Q(away_team=team),
                season__league=self.league,
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
        
        return {
            'teams': teams_data,
            'form': results
        }
