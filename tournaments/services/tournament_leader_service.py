from django.db.models import Sum, Count, Avg, Q, F
from games.models import Game, PlayerStat


class TournamentLeaderService:
    def __init__(self, tournament_id, request=None):
        """Initialize the service with a tournament ID.
        
        Args:
            tournament_id: ID of the tournament
            request: The HTTP request object, needed for building absolute URLs
        """
        from tournaments.models import Tournament
        from sports.models import Sport, LeaderCategory
        
        self.tournament = Tournament.objects.select_related("sport").get(pk=tournament_id)
        self.tournament_id = tournament_id
        self.sport = self.tournament.sport
        self.request = request
        
        # Get all completed games in the tournament
        self.games = Game.objects.filter(
            tournament=self.tournament,
            status=Game.Status.COMPLETED
        ).select_related("home_team", "away_team")
        
        # Get all leader categories for this sport
        self.leader_categories = LeaderCategory.objects.filter(
            sport=self.sport
        ).prefetch_related(
            'stat_types',
            'primary_stat',
        ).order_by('name')
    
    def get_tournament_leaders(self, limit=10):
        """Get the top players for each leader category in the tournament.
        
        Args:
            limit: Maximum number of players to return per category
            
        Returns:
            dict: A dictionary containing leader categories and top players
        """
        if not self.games.exists():
            return {"detail": "No completed games found in this tournament"}
        
        # Get all player stats from completed games
        player_stats = PlayerStat.objects.filter(
            game__in=self.games
        ).select_related('player', 'player__user', 'player__team', 'stat_type')
        
        if not player_stats.exists():
            return {"detail": "No player statistics recorded yet"}
        
        leaders_data = []
        
        for category in self.leader_categories:
            # Get the primary stat for this category
            primary_stat = category.primary_stat
            if not primary_stat:
                continue
                
            # Get all stat types in this category
            stat_types = category.stat_types.all()
            
            # Aggregate player statistics for the primary stat
            aggregated_stats = (
                player_stats.filter(stat_type=primary_stat)
                .values(
                    'player__user_id',
                    'player__user__first_name',
                    'player__user__last_name',
                    'player__jersey_number',
                    'player__team_id',
                    'player__team__name',
                    'player__user__profile',
                )
                .annotate(
                    total=Count('id'),  # Count occurrences
                    games_played=Count('game', distinct=True)
                )
                .filter(total__gt=0)
                .order_by('-total')[:limit]
            )
            
            # Format the data
            leaders_list = []
            for player_stat in aggregated_stats:
                # Calculate stats for this player across all stat types in category
                player_all_stats = {}
                for stat_type in stat_types:
                    stat_count = player_stats.filter(
                        player__user_id=player_stat['player__user_id'],
                        stat_type=stat_type
                    ).count()
                    player_all_stats[stat_type.code] = stat_count
                
                player_data = {
                    "player_id": player_stat['player__user_id'],
                    "player_name": f"{player_stat['player__user__first_name']} {player_stat['player__user__last_name']}",
                    "jersey_number": player_stat['player__jersey_number'],
                    "team_id": player_stat['player__team_id'],
                    "team_name": player_stat['player__team__name'],
                    "stats": player_all_stats,
                    "games_played": player_stat['games_played'],
                }
                
                # Add player photo URL if available
                if player_stat['player__user__profile'] and self.request:
                    player_data['profile_url'] = self.request.build_absolute_uri(
                        player_stat['player__user__profile']
                    )
                else:
                    player_data['profile_url'] = None
                
                leaders_list.append(player_data)
            
            if leaders_list:
                # Get stat info for this category
                stat_info = []
                for stat_type in stat_types:
                    stat_info.append({
                        "code": stat_type.code,
                        "name": stat_type.name,
                        "abbreviation": stat_type.display_name or stat_type.code,
                    })
                
                leaders_data.append({
                    "category_id": category.id,
                    "category": category.name,
                    "stats": stat_info,
                    "leaders": leaders_list
                })
        
        return {
            "leaders": leaders_data
        }
