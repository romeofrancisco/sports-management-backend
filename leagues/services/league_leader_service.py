from collections import defaultdict
from django.db.models import Count, Sum, F, Q
from games.models import Game, PlayerStat
from sports.models import Sport, SportStatType, LeaderCategory
from teams.models import Player
from leagues.models import League, Season
from decimal import Decimal


class LeagueLeaderService:
    """
    Service to aggregate player statistics across all seasons in a league
    to determine overall league leaders in different statistical categories.
    """
    def __init__(self, league_id, request=None):
        self.league = League.objects.select_related("sport").get(pk=league_id)
        self.sport = self.league.sport
        self.request = request
          # Get all seasons in this league
        self.seasons = Season.objects.filter(league=self.league)
        
        # Get teams across all seasons in this league
        team_sets = [season.teams.all() for season in self.seasons]
        if team_sets:
            self.teams = list(set().union(*team_sets))
        else:
            self.teams = []
        
        # Get all completed games across all seasons
        self.games = Game.objects.filter(
            season__in=self.seasons,
            status=Game.Status.COMPLETED
        ).select_related("home_team", "away_team")
          # Get all leader categories for this sport
        self.leader_categories = LeaderCategory.objects.filter(
            sport=self.sport
        ).prefetch_related(
            'stat_types',
            'primary_stat',
            'primary_stat__formula',
            'primary_stat__formula__components',
            'primary_stat__formula__components__stat_type'
        ).order_by('name')
        
        # Get ALL stats for this sport (for calculations)
        self.all_stats = SportStatType.objects.filter(
            sport=self.sport
        ).prefetch_related(
            'formula', 
            'formula__components',
            'formula__components__stat_type'
        )
        
        # Separate recording stats and formula stats
        self.recording_stats = self.all_stats.filter(is_record=True)
        self.formula_stats = self.all_stats.filter(formula__isnull=False)
        
        # Get codes for different stat types
        self.recording_abbrevs = list(self.recording_stats.values_list("code", flat=True))
        self.formula_abbrevs = list(self.formula_stats.values_list("code", flat=True))

    def _aggregate_recording_stats(self):
        """Aggregate all recording stats for players across all seasons in the league"""
        filters = {
            "game__in": self.games,
            "stat_type__in": self.recording_stats,
        }
        
        group_by = ["player_id", "player__team", "player__user__first_name", "player__user__last_name", 
                   "player__jersey_number", "stat_type__code", "stat_type__point_value"]
        
        # For set-based sports, include period in the aggregation
        if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
            group_by.append("period")
            
        return (
            PlayerStat.objects.filter(**filters)
            .values(*group_by)
            .annotate(count=Count("id"))
        )

    def _build_initial_summary(self):
        """Build initial data structure to store stats for all players"""
        summary = {}
        
        # Get all players who participated in any game across all seasons
        players = Player.objects.filter(
            Q(team__home_games__in=self.games) | Q(team__away_games__in=self.games)
        ).distinct().select_related("user", "team")
        
        # Import inside method to avoid circular imports
        from games.models import StartingLineup
        
        for player in players:
            stats_structure = {
                "recording_stats": dict.fromkeys(self.recording_abbrevs, 0),
                "calculated_stats": dict.fromkeys(self.formula_abbrevs, 0),
                "ratio_stats": dict.fromkeys(self.formula_abbrevs, None),
                "point_values": {},  # Store point values for each stat
            }
            
            # Count games played by checking StartingLineup and PlayerStat across all seasons
            games_played = StartingLineup.objects.filter(
                game__in=self.games,
                player=player
            ).values('game').distinct().count()
            
            # Ensure player played in at least one game
            if games_played == 0:
                # Check if they have any recorded stats as backup
                games_played = PlayerStat.objects.filter(
                    game__in=self.games,
                    player=player
                ).values('game').distinct().count()
                
            # Default to 1 to avoid division by zero
            games_played = max(1, games_played)            # Get player profile URL
            profile_url = None
            if self.request and player.user.profile:
                try:
                    profile_url = self.request.build_absolute_uri(player.user.profile.url)
                except (ValueError, AttributeError):
                    profile_url = None
            
            # Create short name like "FirstName L."
            short_name = f"{player.user.first_name} {player.user.last_name[0]}."
                
            player_summary = {
                "player_id": player.user.id,
                "player_name": player.user.get_full_name(),
                "short_name": short_name,
                "jersey_number": player.jersey_number,
                "team_id": player.team.id,
                "team_name": player.team.name,
                "team_abbreviation": player.team.abbreviation,
                "profile_url": profile_url,
                "games_played": games_played,  # Add games played count
            }
            
            # Set up period stats for set-based sports
            if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                player_summary["periods"] = {
                    p: {
                        "recording_stats": dict.fromkeys(self.recording_abbrevs, 0),
                        "calculated_stats": dict.fromkeys(self.formula_abbrevs, 0),
                        "ratio_stats": dict.fromkeys(self.formula_abbrevs, None),
                        "point_values": {},  # Store point values for each stat
                    }
                    for p in range(1, 6)  # Assuming max 5 sets for volleyball
                }
            else:
                player_summary.update(stats_structure)
                
            summary[player.pk] = player_summary
        
        return summary

    def _populate_recording_stats(self, summary):
        """Add all recorded stats to the summary"""
        for rec in self._aggregate_recording_stats():
            pid = rec["player_id"]
            team_id = rec["player__team"]
            abbr = rec["stat_type__code"]
            cnt = rec["count"]
            point_value = rec["stat_type__point_value"]
            
            if pid not in summary:
                continue
                
            if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                per = rec["period"]
                if per <= 5:  # Assuming max 5 sets
                    summary[pid]["periods"][per]["recording_stats"][abbr] = cnt
                    summary[pid]["periods"][per]["point_values"][abbr] = point_value
            else:
                summary[pid]["recording_stats"][abbr] = cnt
                summary[pid]["point_values"][abbr] = point_value

    def _compute_formula_stats(self, summary):
        """Calculate formula-based stats for all players"""
        # Build dependency graph
        dependency_graph = {}
        for stat in self.formula_stats:
            if not stat.formula:
                continue
                
            components = stat.formula.components.all().order_by('order')
            component_codes = [comp.stat_type.code for comp in components]
            dependency_graph[stat.code] = {
                'stat': stat,
                'dependencies': set(component_codes),
                'is_ratio': stat.formula.is_ratio and len(component_codes) == 2,
                'uses_point_value': stat.formula.uses_point_value
            }
        
        # Get stats in correct processing order (dependencies first)
        ordered_stats = []
        in_progress = set()
        
        def process_stat(stat_code):
            if stat_code in ordered_stats:
                return True
            if stat_code in in_progress:
                return False
            
            stat_info = dependency_graph.get(stat_code)
            if not stat_info:
                return True
            
            in_progress.add(stat_code)
            
            for dep in stat_info['dependencies']:
                if dep in dependency_graph and not process_stat(dep):
                    return False
            
            in_progress.remove(stat_code)
            ordered_stats.append(stat_info['stat'])
            return True
        
        for stat_code in dependency_graph:
            if not process_stat(stat_code):
                ordered_stats = [info['stat'] for info in dependency_graph.values()]
                break
        
        # Process formulas in dependency order
        for stat in ordered_stats:
            components = stat.formula.components.all().order_by('order')
            component_codes = [comp.stat_type.code for comp in components]
            is_ratio_stat = stat.formula.is_ratio and len(component_codes) == 2
            uses_point_value = stat.formula.uses_point_value
            decimal_places = stat.formula.decimal_places
            
            for data in summary.values():
                if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                    for pd in data["periods"].values():
                        variables = {}
                        for code in component_codes:
                            # Use point value instead of count if the formula requires it
                            if uses_point_value and code in pd["point_values"]:
                                recording_val = pd["recording_stats"].get(code, 0) * pd["point_values"][code]
                            else:
                                recording_val = pd["recording_stats"].get(code, 0) or 0
                                
                            calc_val = pd["calculated_stats"].get(code, 0) or 0
                            variables[code] = recording_val + calc_val
                        
                        if is_ratio_stat:
                            made = variables[component_codes[0]]
                            attempted = variables[component_codes[1]]
                            
                            if attempted > 0:
                                value = round(Decimal(made) / Decimal(attempted), decimal_places)
                                pd["calculated_stats"][stat.code] = value
                            else:
                                pd["calculated_stats"][stat.code] = 0
                                
                            # Store the ratio as a string (made/attempted)
                            pd["ratio_stats"][stat.code] = f"{made}/{attempted}"
                        else:
                            if stat.formula.expression:
                                try:
                                    value = eval(stat.formula.expression, {"__builtins__": {}}, variables)
                                    pd["calculated_stats"][stat.code] = round(value, decimal_places)
                                except Exception:
                                    pd["calculated_stats"][stat.code] = 0
                            else:
                                pd["calculated_stats"][stat.code] = 0
                else:
                    variables = {}
                    for code in component_codes:
                        # Use point value instead of count if the formula requires it
                        if uses_point_value and code in data["point_values"]:
                            recording_val = data["recording_stats"].get(code, 0) * data["point_values"][code]
                        else:
                            recording_val = data["recording_stats"].get(code, 0) or 0
                            
                        calc_val = data["calculated_stats"].get(code, 0) or 0
                        variables[code] = recording_val + calc_val
                    
                    if is_ratio_stat:
                        made = variables[component_codes[0]]
                        attempted = variables[component_codes[1]]
                        
                        if attempted > 0:
                            value = round(Decimal(made) / Decimal(attempted), decimal_places)
                            data["calculated_stats"][stat.code] = value
                        else:
                            data["calculated_stats"][stat.code] = 0
                            
                        # Store the ratio as a string (made/attempted)
                        data["ratio_stats"][stat.code] = f"{made}/{attempted}"
                    else:
                        if stat.formula.expression:
                            try:
                                value = eval(stat.formula.expression, {"__builtins__": {}}, variables)
                                data["calculated_stats"][stat.code] = round(value, decimal_places)
                            except Exception:
                                data["calculated_stats"][stat.code] = 0
                        else:
                            data["calculated_stats"][stat.code] = 0

    def _find_leaders(self, summary):
        """Find top 5 players across all seasons for each leader category"""
        # Get a flat list of all players
        all_players = list(summary.values())
        
        leaders = []
        
        # Process each leader category
        for category in self.leader_categories:
            category_name = category.name
            primary_stat = category.primary_stat
            
            if not primary_stat:
                continue
                
            primary_code = primary_stat.code
            is_ratio = primary_stat.formula and primary_stat.formula.is_ratio
            
            # List to store all player stats for this category
            player_stats = []
            
            # Calculate stats for each player
            for player in all_players:
                # For set-based sports, calculate total across all periods
                if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                    total_value = 0
                    for period_data in player["periods"].values():
                        if is_ratio:
                            # For ratio stats, use the calculated value (percentage)
                            period_val = period_data["calculated_stats"].get(primary_code, 0) or 0
                            total_value += period_val
                        else:
                            # For regular stats, add up recorded and calculated values
                            recording_val = period_data["recording_stats"].get(primary_code, 0) or 0
                            calc_val = period_data["calculated_stats"].get(primary_code, 0) or 0
                            period_val = recording_val + calc_val
                            total_value += period_val
                    
                    # Calculate per-game average
                    player_value = round(total_value / player["games_played"], 2)
                else:
                    # For points-based sports
                    if is_ratio:
                        # For ratio stats, use the calculated value (percentage)
                        ratio_value = player["calculated_stats"].get(primary_code)
                        if ratio_value is not None:
                            player_value = ratio_value  # Ratios are already averages (makes/attempts)
                        else:
                            player_value = 0
                    else:
                        # For regular stats, add up recorded and calculated values and then calculate average
                        recording_val = player["recording_stats"].get(primary_code, 0) or 0
                        calc_val = player["calculated_stats"].get(primary_code, 0) or 0
                        total_value = recording_val + calc_val
                        
                        # Calculate per-game average
                        player_value = round(total_value / player["games_played"], 2)
                
                # Add player to the list with their stat value
                player_stats.append({
                    "player": player,
                    "value": player_value
                })
            
            # Sort players by their stat values (highest first)
            player_stats.sort(key=lambda x: x["value"], reverse=True)
            
            # Take only the top 5 players
            top_players = player_stats[:5]
            
            # Only include categories with leaders
            if top_players:
                # Get all stats that belong to this leader category
                category_stats = list(category.stat_types.all())
                
                # Rearrange stats to ensure primary stat is first
                # Find the primary stat in the category stats
                primary_stat_index = next((i for i, stat in enumerate(category_stats) 
                                          if stat.code == primary_code), None)
                
                # If primary stat is found and not already at index 0, move it to the front
                if primary_stat_index is not None and primary_stat_index > 0:
                    primary_stat = category_stats.pop(primary_stat_index)
                    category_stats.insert(0, primary_stat)
                
                # Generate stats for top players
                leaders_data = {
                    "category": category_name,
                    "category_id": category.id,
                    "stats": [
                        {
                            "code": stat.code,
                            "name": stat.name,
                            "display_name": stat.display_name or stat.name,
                        } 
                        for stat in category_stats
                    ],
                    "leaders": []
                }
                
                # Add each top player
                for leader_data in top_players:
                    player = leader_data["player"]
                    leader_stats = {}
                    
                    # Add stats for this leader (in the same order as category_stats, with primary stat first)
                    for stat in category_stats:
                        code = stat.code
                        is_stat_ratio = stat.formula and stat.formula.is_ratio
                        
                        # Handle set-based sports
                        if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                            if is_stat_ratio:
                                # For ratio stats, get the combined ratio string
                                makes_total = 0
                                attempts_total = 0
                                for period_data in player["periods"].values():
                                    ratio_str = period_data["ratio_stats"].get(code)
                                    if ratio_str:
                                        parts = ratio_str.split('/')
                                        if len(parts) == 2:
                                            makes_total += int(parts[0])
                                            attempts_total += int(parts[1])
                                
                                if attempts_total > 0:
                                    leader_stats[code] = f"{makes_total}/{attempts_total}"
                                else:
                                    leader_stats[code] = "0/0"
                            else:
                                # For regular stats, calculate average per game
                                total = 0
                                for period_data in player["periods"].values():
                                    recording_val = period_data["recording_stats"].get(code, 0) or 0
                                    calc_val = period_data["calculated_stats"].get(code, 0) or 0
                                    total += recording_val + calc_val
                                
                                avg = round(total / player["games_played"], 2)
                                leader_stats[code] = f"{avg}"
                        else:
                            # For regular sports
                            if is_stat_ratio:
                                # For ratio stats, use the stored ratio
                                leader_stats[code] = player["ratio_stats"].get(code, "0/0")
                            else:
                                # For regular stats, calculate average per game
                                recording_val = player["recording_stats"].get(code, 0) or 0
                                calc_val = player["calculated_stats"].get(code, 0) or 0
                                total = recording_val + calc_val
                                avg = round(total / player["games_played"], 2)
                                leader_stats[code] = f"{avg}"
                    
                    # Add this leader to the results
                    leaders_data["leaders"].append({
                        "player_id": player["player_id"],
                        "player_name": player["player_name"],
                        "short_name": player["short_name"],
                        "jersey_number": player["jersey_number"],
                        "team_id": player["team_id"],
                        "team_name": player["team_name"],
                        "team_abbreviation": player["team_abbreviation"],
                        "profile": player.get("profile_url"),
                        "stats": leader_stats,
                        "games_played": player["games_played"]
                    })
                
                leaders.append(leaders_data)
        
        return leaders

    def get_league_leaders(self):
        """Main method to get league leaders across all seasons"""
        summary = self._build_initial_summary()
        self._populate_recording_stats(summary)  # First populate recording stats
        self._compute_formula_stats(summary)     # Then compute formula-based stats
        leaders = self._find_leaders(summary)
        
        return {
            "league_id": self.league.id,
            "league_name": self.league.name,
            "sport": self.sport.name,
            "seasons_count": self.seasons.count(),
            "teams": [
                {
                    "team_id": team.id,
                    "team_name": team.name,
                    "team_abbreviation": team.abbreviation,
                }
                for team in self.teams
            ],
            "leaders": leaders
        }
