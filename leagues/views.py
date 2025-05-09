from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from .models import League, Season
from .serializers import LeagueSerializer, LeagueWriteSerializer, SeasonSerializer, TeamStandingsSerializer, LeagueStatisticsSerializer, SeasonComparisonSerializer
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum, Avg, F, Q, Func
from teams.models import Team
from sports.models import Sport


# Custom pagination class specifically for seasons
class SeasonPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50

class LeagueViewSet(viewsets.ModelViewSet):
    queryset = League.objects.all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return LeagueWriteSerializer
        return LeagueSerializer
    
    @action(detail=True, methods=["get"])
    def standings(self, request, pk=None):
        league = self.get_object()
        
        # Get the properly sorted standings from the backend
        raw_standings = league.standings(request=request)
        
        # Extract team IDs in the correct sorted order
        team_ids_in_order = [item['team_id'] for item in raw_standings]
        
        # Return the raw standings directly to maintain the proper order
        return Response(raw_standings)
    
    @action(detail=True, methods=["get"])
    def statistics(self, request, pk=None):
        """Get comprehensive league statistics for the dashboard"""
        league = self.get_object()
        
        # Get all completed games in the league
        all_games = league.seasons.prefetch_related('games').filter(
            games__status="completed"
        )
        
        # Count teams, seasons, games
        teams_count = league.seasons.aggregate(
            total_teams=Count('teams', distinct=True)
        )['total_teams']
        
        seasons_count = league.seasons.count()
        active_seasons = league.seasons.filter(status__in=["ongoing", "upcoming"]).count()
        
        games_count = all_games.count()
        
        # Get current season if any
        current_season = league.seasons.filter(status="ongoing").order_by("-start_date").first()
        
        statistics = {
            "teams_count": teams_count,
            "seasons_count": seasons_count,
            "active_seasons": active_seasons,
            "games_count": games_count,
            "current_season": SeasonSerializer(current_season, context={"request": request}).data if current_season else None,
        }
        
        return Response(statistics)
    
    @action(detail=True, methods=["get"])
    def team_form(self, request, pk=None):
        """Get the recent form for top teams in the league"""
        league = self.get_object()
        
        # Get all teams based on standings instead of limiting to top teams
        teams_data = league.standings(request=request)
        team_ids = [team['team_id'] for team in teams_data]
        
        # Get all teams
        teams = Team.objects.filter(id__in=team_ids)
        
        # Get recent games for each team (last 5)
        results = {}
        
        for team in teams:
            from games.models import Game
            
            recent_games = Game.objects.filter(
                Q(home_team=team) | Q(away_team=team),
                season__league=league,
                status="completed"
            ).order_by('-date')[:5]  # Changed from scheduled_date to date
            
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
                    'date': game.date.strftime("%Y-%m-%d")  # Changed from scheduled_date to date
                })
            
            results[team.id] = team_results
        
        return Response({
            'teams': teams_data,
            'form': results
        })
    
    @action(detail=True, methods=["get"])
    def comprehensive_stats(self, request, pk=None):
        """Get detailed comprehensive statistics for the entire league"""
        league = self.get_object()
        sport = league.sport
        
        # Determine if it's a set-based sport
        is_set_based = sport.scoring_type == Sport.SCORING_TYPES.SETS
        
        # Get all completed games in the league across all seasons
        from games.models import Game, GameSet
        all_games = Game.objects.filter(
            season__league=league,
            status="completed"
        ).select_related('home_team', 'away_team', 'season')
        
        # Calculate total games count
        total_games = all_games.count()
        if (total_games == 0):
            return Response({
                "detail": "No completed games found in this league."
            })
            
        # Get all teams that participated in any season
        all_teams = set()
        for season in league.seasons.all():
            all_teams.update(season.teams.all())
        
        # Calculate wins, losses, win ratios for all teams
        team_stats = {}
        
        # League-wide stats
        if is_set_based:
            # Set-based sport statistics (volleyball, tennis, etc.)
            total_sets_played = GameSet.objects.filter(game__season__league=league).count()
            total_matches = total_games
            avg_sets_per_match = total_sets_played / total_matches if total_matches > 0 else 0
            
            # Set score distribution
            set_scores = GameSet.objects.filter(
                game__season__league=league,
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
            for team in all_teams:
                team_matches = all_games.filter(
                    Q(home_team=team) | Q(away_team=team)
                )
                
                matches_won = team_matches.filter(winner_team=team).count()
                matches_played = team_matches.count()
                
                # Get sets statistics
                sets_played = GameSet.objects.filter(
                    Q(game__home_team=team) | Q(game__away_team=team),
                    game__season__league=league
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
            
            # Sort teams by match win percentage, then by set win percentage
            sorted_teams = sorted(
                team_stats.values(), 
                key=lambda x: (-x['match_win_percentage'], -x['sets_win_percentage'])
            )
            
            # Prepare championship data - which teams won brackets
            from brackets.models import Bracket
            champions = Bracket.objects.filter(
                season__league=league,
                winner__isnull=False
            ).values('season__year', 'winner__name', 'winner__id').order_by('-season__year')
            
            # Compile response
            response = {
                "league_id": league.id,
                "league_name": league.name,
                "sport": sport.name,
                "scoring_type": sport.scoring_type,
                "total_matches": total_matches,
                "total_sets": total_sets_played,
                "avg_sets_per_match": round(avg_sets_per_match, 2),
                "avg_points_per_set": round(avg_points_per_set, 2),
                "common_set_scores": common_scores,
                "teams": sorted_teams,
                "champions": list(champions),
                "seasons_count": league.seasons.count(),
                "completed_seasons": league.seasons.filter(status="completed").count()
            }
        
        else:
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
            for team in all_teams:
                team_games = all_games.filter(
                    Q(home_team=team) | Q(away_team=team)
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
            
            # Sort teams by win percentage, then by point differential
            sorted_teams = sorted(
                team_stats.values(), 
                key=lambda x: (-x['win_percentage'], -x['point_differential'])
            )
            
            # Prepare championship data - which teams won brackets
            from brackets.models import Bracket
            champions = Bracket.objects.filter(
                season__league=league,
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
                "league_id": league.id,
                "league_name": league.name,
                "sport": sport.name,
                "scoring_type": sport.scoring_type,
                "total_games": total_games,
                "avg_points_per_game": round(avg_points_per_game, 2),
                "highest_scoring_games": high_scoring_games,
                "biggest_margin_games": margin_games,
                "teams": sorted_teams,
                "champions": list(champions),
                "seasons_count": league.seasons.count(),
                "completed_seasons": league.seasons.filter(status="completed").count()
            }
            
        return Response(response)

class SeasonViewSet(viewsets.ModelViewSet):
    serializer_class = SeasonSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = SeasonPagination

    def get_queryset(self):
        return Season.objects.filter(league_id=self.kwargs['league_pk'])

    def perform_create(self, serializer):
        league = get_object_or_404(League, pk=self.kwargs['league_pk'])
        serializer.save(league=league)
    
    @action(detail=True, methods=["post"])
    def manage(self, request, pk=None, **kwargs):
        season = self.get_object()
        action_type = request.data.get("action")

        try:
            if action_type == "start":
                season.start_season()
                return Response({"detail": "Season started."}, status=status.HTTP_200_OK)

            elif action_type == "complete":
                season.complete_season()
                return Response({"detail": "Season completed."}, status=status.HTTP_200_OK)

            elif action_type == "pause":
                season.pause_season()
                return Response({"detail": "Season paused."}, status=status.HTTP_200_OK)

            elif action_type == "cancel":
                season.cancel_season()
                return Response({"detail": "Season canceled."}, status=status.HTTP_200_OK)

            else:
                return Response({"detail": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)

        except ValidationError as e:
            return Response({"detail": e.message}, status=status.HTTP_400_BAD_REQUEST)
        
    @action(detail=True, methods=['post'])
    def add_team(self, request, pk=None):
        season = self.get_object()
        team_id = request.data.get('team_id')
        
        if not team_id:
            return Response({'error': 'team_id required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if season.teams.filter(id=team_id).exists():
            return Response({'status': 'Team already in season'})
            
        team = Team.objects.get(id=team_id)
        if team.sport != season.sport:
            return Response({'error': 'Team sport mismatch'}, status=400)
            
        season.teams.add(team)
        return Response({'status': 'Team added'})

    @action(detail=True, methods=['post'])
    def remove_team(self, request, pk=None):
        season = self.get_object()
        team_id = request.data.get('team_id')
        
        if not team_id:
            return Response({'error': 'team_id required'}, status=400)
            
        season.teams.remove(team_id)
        return Response({'status': 'Team removed'})
    
    @action(detail=True, methods=['get'])
    def standings(self, request, league_pk=None, pk=None):
        season = self.get_object()
        
        # Get properly sorted standings from the backend
        raw_standings = season.standings()
        
        # Instead of using the teams.all() which loses the sort order,
        # we'll extract team IDs in the correct sorted order from raw_standings
        team_ids_in_order = [item['team_id'] for item in raw_standings]
        
        # Create a mapping of team_id to standings data for quick lookup
        standings_data = {item['team_id']: item for item in raw_standings}
        
        # Get the Team objects but preserve the sorted order from raw_standings
        from teams.models import Team
        teams = []
        for team_id in team_ids_in_order:
            try:
                teams.append(Team.objects.get(id=team_id))
            except Team.DoesNotExist:
                pass
        
        # Use the serializer with the ordered teams
        serializer = TeamStandingsSerializer(
            teams,
            many=True,
            context={
                'request': request,
                'standings_data': standings_data
            }
        )
        
        return Response(serializer.data)
        
    @action(detail=True, methods=['get'])
    def team_performance(self, request, league_pk=None, pk=None):
        """Get detailed performance metrics for teams in a season"""
        try:
            season = self.get_object()
        except Season.DoesNotExist:
            return Response(
                {"detail": "Season not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get the sport type to determine scoring metrics
        sport = season.league.sport
        is_set_based = sport.scoring_type == Sport.SCORING_TYPES.SETS
        
        # Get completed games in this season
        from games.models import Game, GameSet
        games = Game.objects.filter(
            season=season,
            status="completed"
        ).select_related('home_team', 'away_team')
        
        # Calculate team performance metrics
        teams = season.teams.all()
        team_performance = []
        
        for team in teams:
            # Get all games involving this team
            team_games = games.filter(
                Q(home_team=team) | Q(away_team=team)
            )
            
            games_count = team_games.count()
            
            if is_set_based:
                # For set-based sports like volleyball, tennis
                
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
                            total_points_scored += game.home_team_score
                            total_points_conceded += game.away_team_score
                            if game.winner == team:
                                sets_won += 1
                                
                            # Calculate set efficiency for this single-set game
                            total_points = game.home_team_score + game.away_team_score
                            if total_points > 0:
                                total_set_efficiency += (game.home_team_score / total_points) * 100
                        else:  # Away team
                            total_points_scored += game.away_team_score
                            total_points_conceded += game.home_team_score
                            if game.winner == team:
                                sets_won += 1
                                
                            # Calculate set efficiency for this single-set game
                            total_points = game.home_team_score + game.away_team_score
                            if total_points > 0:
                                total_set_efficiency += (game.away_team_score / total_points) * 100
                    else:
                        # Process all individual sets
                        for game_set in game_sets:
                            if game.home_team == team:
                                # Team is home team
                                total_points_scored += game_set.home_team_score
                                total_points_conceded += game_set.away_team_score
                                if game_set.winner == team:
                                    sets_won += 1
                            else:  # Away team
                                total_points_scored += game_set.away_team_score
                                total_points_conceded += game_set.home_team_score
                                if game_set.winner == team:
                                    sets_won += 1
                            
                            total_sets_played += 1
                            
                            # Calculate set efficiency (% of total points won)
                            points_in_set = game_set.home_team_score + game_set.away_team_score
                            team_points = game_set.home_team_score if game.home_team == team else game_set.away_team_score
                            if points_in_set > 0:
                                total_set_efficiency += (team_points / points_in_set) * 100
                
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
                
                # Use relevant set-based metrics
                performance = {
                    'team_id': team.id,
                    'team_name': team.name,
                    'team_slug': team.slug,
                    'team_logo': request.build_absolute_uri(team.logo.url) if team.logo and request else None,
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
                    'points_against_per_set': points_against_per_set
                }
                
                # Add first half and second half performance
                # Calculate this based on match wins rather than set wins
                first_half_wins = 0
                second_half_wins = 0
                
                half_count = len(team_games) // 2
                first_half_games = list(team_games.order_by('date'))[:half_count]
                second_half_games = list(team_games.order_by('date'))[half_count:]
                
                for game in first_half_games:
                    if game.winner == team:
                        first_half_wins += 1
                
                for game in second_half_games:
                    if game.winner == team:
                        second_half_wins += 1
                
                performance.update({
                    'first_half_wins': first_half_wins,
                    'second_half_wins': second_half_wins,
                })
                
                # Calculate streak based on matches
                current_streak = 0
                max_streak = 0
                
                for game in team_games.order_by('date'):
                    is_win = game.winner == team
                    
                    if is_win:
                        current_streak = current_streak + 1 if current_streak >= 0 else 1
                    else:
                        current_streak = current_streak - 1 if current_streak <= 0 else -1
                    
                    max_streak = max(max_streak, current_streak)
                
                performance.update({
                    'max_streak': max_streak,
                    'current_streak': current_streak,
                    'total_games': games_count
                })
                
            else:
                # Original code for point-based sports
                points_scored = 0
                points_conceded = 0
                
                for game in team_games:
                    if game.home_team == team:
                        points_scored += game.home_team_score
                        points_conceded += game.away_team_score
                    else:
                        points_scored += game.away_team_score
                        points_conceded += game.home_team_score
                        
                # Calculate averages
                avg_points_scored = points_scored / games_count if games_count > 0 else 0
                avg_points_conceded = points_conceded / games_count if games_count > 0 else 0
                
                # Get first and second half performance
                first_half_wins = 0
                second_half_wins = 0
                
                half_count = len(team_games) // 2
                first_half_games = list(team_games.order_by('date'))[:half_count]
                second_half_games = list(team_games.order_by('date'))[half_count:]
                
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
                    'team_logo': request.build_absolute_uri(team.logo.url) if team.logo and request else None,
                    'games_played': games_count,
                    'avg_points_scored': round(avg_points_scored, 2),
                    'avg_points_conceded': round(avg_points_conceded, 2),
                    'first_half_wins': first_half_wins,
                    'second_half_wins': second_half_wins,
                    'point_differential': round(avg_points_scored - avg_points_conceded, 2),
                    'max_streak': max_streak,
                    'current_streak': current_streak,
                    'total_games': games_count
                }
            
            team_performance.append(performance)
        
        # Sort by appropriate metric
        if is_set_based:
            # Sort by set win percentage for set-based sports
            team_performance.sort(key=lambda x: (-x['match_win_percentage'], -x['set_win_percentage']))
        else:
            # Sort by point differential for point-based sports
            team_performance.sort(key=lambda x: -x['point_differential'])
        
        return Response(team_performance)
        
    @action(detail=False, methods=['get'])
    def comparison(self, request, league_pk=None):
        """Compare multiple seasons in the same league"""
        league = get_object_or_404(League, pk=league_pk)
        seasons_ids = request.query_params.get('seasons', '').split(',')
        
        if not seasons_ids or not seasons_ids[0]:
            # Default to all completed seasons
            seasons = Season.objects.filter(
                league=league, 
                status='completed'
            ).order_by('-year')[:5]
        else:
            seasons = Season.objects.filter(
                league=league, 
                id__in=seasons_ids
            )
        
        comparison_data = []
        
        for season in seasons:
            # Get season standings
            standings = season.standings()
            
            # Get season games
            from games.models import Game
            games = Game.objects.filter(
                season=season,
                status="completed"
            )
            
            # Calculate average points per game
            total_points = sum(game.home_team_score + game.away_team_score for game in games)
            avg_points_per_game = total_points / games.count() if games.count() > 0 else 0
            
            # Find champion
            from brackets.models import Bracket
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
            
        return Response(comparison_data)
        
    @action(detail=True, methods=['get'])
    def games(self, request, league_pk=None, pk=None):
        """Get all games in a season with filtering options"""
        season = self.get_object()
        
        # Get games for this season
        from games.models import Game
        from games.serializers import GameSerializer
        
        games = Game.objects.filter(season=season).select_related(
            'home_team', 'away_team', 'season'
        ).order_by('date')
        
        # Apply filters if provided
        status = request.query_params.get('status')
        if status:
            games = games.filter(status=status)
            
        team_id = request.query_params.get('team')
        if team_id:
            games = games.filter(Q(home_team_id=team_id) | Q(away_team_id=team_id))
            
        # Filter by date if provided (exact date match)
        date = request.query_params.get('date')
        if date:
            from datetime import datetime
            try:
                # Parse the date and filter games on that specific date
                parsed_date = datetime.strptime(date, '%Y-%m-%d').date()
                games = games.filter(date__date=parsed_date)
            except ValueError:
                pass
            
        # Serialize and return
        serializer = GameSerializer(games, many=True, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def teams(self, request, league_pk=None, pk=None):
        """Get all teams in a season with extended information"""
        season = self.get_object()
        
        # Get teams for this season
        from teams.models import Team
        from teams.serializers import TeamSerializer
        
        # Changed 'coaches' to 'coach' to match the field name in the Team model
        teams = season.teams.prefetch_related('coach', 'players').all()
        
        # Get win/loss records for each team
        from django.db.models import Q, Count, Case, When, IntegerField, F, Sum
        from games.models import Game
        
        team_stats = {}
        for team in teams:
            games = Game.objects.filter(
                Q(home_team=team) | Q(away_team=team),
                season=season,
                status='completed'
            )
            
            # Get win/loss record
            wins = 0
            losses = 0
            games_played = games.count()
            
            # Calculate recent form (last 5 games)
            form = ""
            recent_games = games.order_by('-date')[:5]
            
            for game in games:
                if game.home_team == team:
                    if game.home_team_score > game.away_team_score:
                        wins += 1
                    else:
                        losses += 1
                else:  # away team
                    if game.away_team_score > game.home_team_score:
                        wins += 1
                    else:
                        losses += 1
            
            # Generate form string (W for win, L for loss)
            for game in recent_games:
                if game.home_team == team:
                    form += "W" if game.home_team_score > game.away_team_score else "L"
                else:
                    form += "W" if game.away_team_score > game.home_team_score else "L"
            
            team_stats[team.id] = {
                'wins': wins,
                'losses': losses,
                'games_played': games_played,
                'form': form
            }
        
        # Combine team data with stats
        serializer = TeamSerializer(teams, many=True, context={'request': request})
        team_data = serializer.data
        
        # Add stats to each team
        for team in team_data:
            team_id = team['id']
            if team_id in team_stats:
                team.update(team_stats[team_id])
        
        # Sort by wins (descending)
        team_data = sorted(team_data, key=lambda x: x.get('wins', 0), reverse=True)
        
        return Response(team_data)
    
    @action(detail=True, methods=['get'])
    def team_form(self, request, league_pk=None, pk=None):
        """Get the recent form for teams in a season"""
        season = self.get_object()
        
        # Get all teams in this season based on standings
        raw_standings = season.standings()
        team_ids = [team['team_id'] for team in raw_standings]
        
        # Get all teams
        teams = Team.objects.filter(id__in=team_ids)
        
        # Get recent games for each team (last 5)
        results = {}
        
        for team in teams:
            from games.models import Game
            
            recent_games = Game.objects.filter(
                Q(home_team=team) | Q(away_team=team),
                season=season,
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
        
        return Response({
            'teams': raw_standings,
            'form': results
        })