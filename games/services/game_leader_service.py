from collections import defaultdict
from django.db.models import Count, Sum
from games.models import Game, PlayerStat
from sports.models import Sport, SportStatType, LeaderCategory
from teams.models import Player


class GameLeaderService:
    def __init__(self, game_id, request=None):
        self.game = Game.objects.select_related("home_team", "away_team", "sport").get(pk=game_id)
        self.teams = [self.game.home_team, self.game.away_team]
        self.request = request
          # Get all leader categories for this sport
        self.leader_categories = LeaderCategory.objects.filter(
            sport=self.game.sport
        ).prefetch_related(
            'stat_types',
            'primary_stat',
            'primary_stat__formula',
            'primary_stat__formula__components',
            'primary_stat__formula__components__stat_type'
        ).order_by('name')
        
        # Get ALL stats for this sport (for calculations)
        self.all_stats = SportStatType.objects.filter(
            sport=self.game.sport
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
        filters = {
            "game": self.game,
            "stat_type__in": self.recording_stats,
        }
        
        # Only include period in grouping for set-based sports
        group_by = ["player_id", "player__team", "player__user__first_name", "player__user__last_name", 
                   "player__jersey_number", "stat_type__code", "stat_type__point_value"]
        if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
            group_by.append("period")
            
        return (
            PlayerStat.objects.filter(**filters)
            .values(*group_by)
            .annotate(count=Count("id"))
        )

    def _build_initial_summary(self):
        summary = {}
        for team in self.teams:
            team_players = Player.objects.filter(team=team).select_related("user")
            
            for player in team_players:
                stats_structure = {
                    "recording_stats": dict.fromkeys(self.recording_abbrevs, 0),
                    "calculated_stats": dict.fromkeys(self.formula_abbrevs, 0),
                    "ratio_stats": dict.fromkeys(self.formula_abbrevs, None),
                    "point_values": {},  # Store point values for each stat
                }                # Get player profile URL
                profile_url = None
                if self.request and player.user.profile:
                    profile_url = self.request.build_absolute_uri(player.user.profile.url)
                
                # Create short name like "FirstName L."
                short_name = f"{player.user.first_name[0]}. {player.user.last_name}"
                
                player_summary = {
                    "player_id": player.user.id,
                    "player_name": player.user.get_full_name(),
                    "short_name": short_name,
                    "jersey_number": player.jersey_number,
                    "team_id": player.team.id,
                    "profile_url": profile_url,
                }
                
                # Only include periods for set-based sports
                if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                    player_summary["periods"] = {
                        p: {
                            "recording_stats": dict.fromkeys(self.recording_abbrevs, 0),
                            "calculated_stats": dict.fromkeys(self.formula_abbrevs, 0),
                            "ratio_stats": dict.fromkeys(self.formula_abbrevs, None),
                            "point_values": {},  # Store point values for each stat
                        }
                        for p in range(1, self.game.current_period + 1)
                    }
                else:
                    player_summary.update(stats_structure)
                    
                summary[player.pk] = player_summary
        return summary

    def _populate_recording_stats(self, summary):
        for rec in self._aggregate_recording_stats():
            pid = rec["player_id"]
            team_id = rec["player__team"]
            abbr = rec["stat_type__code"]
            cnt = rec["count"]
            point_value = rec["stat_type__point_value"]
            
            if pid not in summary:
                continue
                
            if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                per = rec["period"]
                if per <= self.game.current_period:
                    summary[pid]["periods"][per]["recording_stats"][abbr] = cnt
                    summary[pid]["periods"][per]["point_values"][abbr] = point_value
            else:
                summary[pid]["recording_stats"][abbr] = cnt
                summary[pid]["point_values"][abbr] = point_value

    def _compute_formula_stats(self, summary):
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
                if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                    for pd in data["periods"].values():
                        variables = {}
                        for code in component_codes:
                            # Use point value instead of count if the formula requires it
                            if uses_point_value and code in pd["point_values"]:
                                recording_val = pd["recording_stats"].get(code, 0) * pd["point_values"].get(code, 0)
                            else:
                                recording_val = pd["recording_stats"].get(code, 0) or 0
                                
                            calc_val = pd["calculated_stats"].get(code, 0) or 0
                            variables[code] = recording_val + calc_val
                        
                        if is_ratio_stat:
                            made = variables[component_codes[0]]
                            attempted = variables[component_codes[1]]
                            pd["calculated_stats"][stat.code] = None
                            pd["ratio_stats"][stat.code] = f"{made}/{attempted}"
                        else:
                            if stat.formula.expression:
                                try:
                                    result = eval(stat.formula.expression, {}, variables)
                                    if isinstance(result, float):
                                        result = round(result, decimal_places)
                                    pd["calculated_stats"][stat.code] = result
                                except:
                                    pd["calculated_stats"][stat.code] = 0
                            else:
                                pd["calculated_stats"][stat.code] = 0
                else:
                    variables = {}
                    for code in component_codes:
                        # Use point value instead of count if the formula requires it
                        if uses_point_value and code in data["point_values"]:
                            recording_val = data["recording_stats"].get(code, 0) * data["point_values"].get(code, 0)
                        else:
                            recording_val = data["recording_stats"].get(code, 0) or 0
                            
                        calc_val = data["calculated_stats"].get(code, 0) or 0
                        variables[code] = recording_val + calc_val
                    
                    if is_ratio_stat:
                        made = variables[component_codes[0]]
                        attempted = variables[component_codes[1]]
                        data["calculated_stats"][stat.code] = None
                        data["ratio_stats"][stat.code] = f"{made}/{attempted}"
                    else:
                        if stat.formula.expression:
                            try:
                                result = eval(stat.formula.expression, {}, variables)
                                if isinstance(result, float):
                                    result = round(result, decimal_places)
                                data["calculated_stats"][stat.code] = result
                            except:
                                data["calculated_stats"][stat.code] = 0
                        else:
                            data["calculated_stats"][stat.code] = 0

    def _find_team_leaders(self, summary):
        home_team_id = self.game.home_team.id
        away_team_id = self.game.away_team.id
        
        # Organize players by team
        home_team_players = []
        away_team_players = []
        
        for pid, data in summary.items():
            if data["team_id"] == home_team_id:
                home_team_players.append(data)
            elif data["team_id"] == away_team_id:
                away_team_players.append(data)
                
        leaders = []
        
        # Process each leader category
        for category in self.leader_categories:
            category_name = category.name
            primary_stat = category.primary_stat
            
            if not primary_stat:
                continue
                
            primary_code = primary_stat.code
            is_ratio = primary_stat.formula and primary_stat.formula.is_ratio
            
            # Find home team leader
            home_leader = None
            home_leader_value = None
            
            # Find away team leader
            away_leader = None
            away_leader_value = None
            
            # For set-based sports, we need to aggregate stats across periods
            if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                for player in home_team_players:
                    player_total = 0
                    for period_data in player["periods"].values():
                        if is_ratio:
                            # For ratio stats, we need to sum the components
                            ratio_value = period_data["ratio_stats"].get(primary_code)
                            if ratio_value:
                                try:
                                    made, attempted = map(int, ratio_value.split('/'))
                                    # Add to player total
                                    player_total += made
                                except (ValueError, AttributeError):
                                    pass
                        else:
                            # For regular stats, just sum the values
                            recording_val = period_data["recording_stats"].get(primary_code, 0) or 0
                            calc_val = period_data["calculated_stats"].get(primary_code, 0) or 0
                            player_total += recording_val + calc_val
                    
                    # Check if this player is the new leader
                    if home_leader is None or player_total > home_leader_value:
                        home_leader = player
                        home_leader_value = player_total
                
                for player in away_team_players:
                    player_total = 0
                    for period_data in player["periods"].values():
                        if is_ratio:
                            # For ratio stats, we need to sum the components
                            ratio_value = period_data["ratio_stats"].get(primary_code)
                            if ratio_value:
                                try:
                                    made, attempted = map(int, ratio_value.split('/'))
                                    # Add to player total
                                    player_total += made
                                except (ValueError, AttributeError):
                                    pass
                        else:
                            # For regular stats, just sum the values
                            recording_val = period_data["recording_stats"].get(primary_code, 0) or 0
                            calc_val = period_data["calculated_stats"].get(primary_code, 0) or 0
                            player_total += recording_val + calc_val
                    
                    # Check if this player is the new leader
                    if away_leader is None or player_total > away_leader_value:
                        away_leader = player
                        away_leader_value = player_total
            else:
                # For points-based sports, it's more straightforward
                for player in home_team_players:
                    if is_ratio:
                        # For ratio stats, extract the first number (makes)
                        ratio_value = player["ratio_stats"].get(primary_code)
                        if ratio_value:
                            try:
                                made, attempted = map(int, ratio_value.split('/'))
                                player_value = made
                            except (ValueError, AttributeError):
                                player_value = 0
                        else:
                            player_value = 0
                    else:
                        # For regular stats, combine recording and calculated values
                        recording_val = player["recording_stats"].get(primary_code, 0) or 0
                        calc_val = player["calculated_stats"].get(primary_code, 0) or 0
                        player_value = recording_val + calc_val
                    
                    # Check if this player is the new leader
                    if home_leader is None or player_value > home_leader_value:
                        home_leader = player
                        home_leader_value = player_value
                
                for player in away_team_players:
                    if is_ratio:
                        # For ratio stats, extract the first number (makes)
                        ratio_value = player["ratio_stats"].get(primary_code)
                        if ratio_value:
                            try:
                                made, attempted = map(int, ratio_value.split('/'))
                                player_value = made
                            except (ValueError, AttributeError):
                                player_value = 0
                        else:
                            player_value = 0
                    else:
                        # For regular stats, combine recording and calculated values
                        recording_val = player["recording_stats"].get(primary_code, 0) or 0
                        calc_val = player["calculated_stats"].get(primary_code, 0) or 0
                        player_value = recording_val + calc_val
                    
                    # Check if this player is the new leader
                    if away_leader is None or player_value > away_leader_value:
                        away_leader = player
                        away_leader_value = player_value
            
            # Only proceed if we have found leaders for both teams
            if home_leader and away_leader:
                # Get all stats that belong to this leader category
                category_stats = category.stat_types.all()
                
                # Generate stats for home team leader
                home_leader_stats = {}
                
                # First add the primary stat (this will be used for ranking)
                if is_ratio:
                    # For ratio stats, get the actual ratio string
                    if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                        home_makes = home_leader_value
                        home_attempts = 0
                        
                        # Calculate total attempts
                        for period_data in home_leader["periods"].values():
                            ratio_value = period_data["ratio_stats"].get(primary_code)
                            if ratio_value:
                                try:
                                    _, attempted = map(int, ratio_value.split('/'))
                                    home_attempts += attempted
                                except (ValueError, AttributeError):
                                    pass
                        
                        home_leader_stats[primary_stat.code] = f"{home_makes}/{home_attempts}"
                    else:
                        home_leader_stats[primary_stat.code] = home_leader["ratio_stats"].get(primary_code, "0/0")
                else:
                    # For regular stats, just format the number
                    if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                        home_leader_stats[primary_stat.code] = str(home_leader_value)
                    else:
                        home_recording = home_leader["recording_stats"].get(primary_code, 0) or 0
                        home_calc = home_leader["calculated_stats"].get(primary_code, 0) or 0
                        home_leader_stats[primary_stat.code] = str(home_recording + home_calc)
                
                # Now add all other stats from the category
                for stat in category_stats:
                    if stat.code != primary_code:  # Skip primary stat as we've already processed it
                        code = stat.code
                        is_stat_ratio = stat.formula and stat.formula.is_ratio
                        
                        # Process for set-based sports
                        if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                            if is_stat_ratio:
                                # For ratio stats, accumulate across periods
                                makes = 0
                                attempts = 0
                                
                                for period_data in home_leader["periods"].values():
                                    ratio_value = period_data["ratio_stats"].get(code)
                                    if ratio_value:
                                        try:
                                            made, attempted = map(int, ratio_value.split('/'))
                                            makes += made
                                            attempts += attempted
                                        except (ValueError, AttributeError):
                                            pass
                                
                                home_leader_stats[code] = f"{makes}/{attempts}" if attempts > 0 else "0/0"
                            else:
                                # For non-ratio stats, sum across periods
                                total = 0
                                for period_data in home_leader["periods"].values():
                                    recording_val = period_data["recording_stats"].get(code, 0) or 0
                                    calc_val = period_data["calculated_stats"].get(code, 0) or 0
                                    total += recording_val + calc_val
                                
                                home_leader_stats[code] = str(total)
                        else:
                            # For points-based sports
                            if is_stat_ratio:
                                home_leader_stats[code] = home_leader["ratio_stats"].get(code, "0/0")
                            else:
                                recording_val = home_leader["recording_stats"].get(code, 0) or 0
                                calc_val = home_leader["calculated_stats"].get(code, 0) or 0
                                home_leader_stats[code] = str(recording_val + calc_val)
                
                # Generate stats for away team leader
                away_leader_stats = {}
                
                # First add the primary stat (this will be used for ranking)
                if is_ratio:
                    # For ratio stats, get the actual ratio string
                    if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                        away_makes = away_leader_value
                        away_attempts = 0
                        
                        # Calculate total attempts
                        for period_data in away_leader["periods"].values():
                            ratio_value = period_data["ratio_stats"].get(primary_code)
                            if ratio_value:
                                try:
                                    _, attempted = map(int, ratio_value.split('/'))
                                    away_attempts += attempted
                                except (ValueError, AttributeError):
                                    pass
                        
                        away_leader_stats[primary_stat.code] = f"{away_makes}/{away_attempts}"
                    else:
                        away_leader_stats[primary_stat.code] = away_leader["ratio_stats"].get(primary_code, "0/0")
                else:
                    # For regular stats, just format the number
                    if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                        away_leader_stats[primary_stat.code] = str(away_leader_value)
                    else:
                        away_recording = away_leader["recording_stats"].get(primary_code, 0) or 0
                        away_calc = away_leader["calculated_stats"].get(primary_code, 0) or 0
                        away_leader_stats[primary_stat.code] = str(away_recording + away_calc)
                
                # Now add all other stats from the category
                for stat in category_stats:
                    if stat.code != primary_code:  # Skip primary stat as we've already processed it
                        code = stat.code
                        is_stat_ratio = stat.formula and stat.formula.is_ratio
                        
                        # Process for set-based sports
                        if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                            if is_stat_ratio:
                                # For ratio stats, accumulate across periods
                                makes = 0
                                attempts = 0
                                
                                for period_data in away_leader["periods"].values():
                                    ratio_value = period_data["ratio_stats"].get(code)
                                    if ratio_value:
                                        try:
                                            made, attempted = map(int, ratio_value.split('/'))
                                            makes += made
                                            attempts += attempted
                                        except (ValueError, AttributeError):
                                            pass
                                
                                away_leader_stats[code] = f"{makes}/{attempts}" if attempts > 0 else "0/0"
                            else:
                                # For non-ratio stats, sum across periods
                                total = 0
                                for period_data in away_leader["periods"].values():
                                    recording_val = period_data["recording_stats"].get(code, 0) or 0
                                    calc_val = period_data["calculated_stats"].get(code, 0) or 0
                                    total += recording_val + calc_val
                                
                                away_leader_stats[code] = str(total)
                        else:
                            # For points-based sports
                            if is_stat_ratio:
                                away_leader_stats[code] = away_leader["ratio_stats"].get(code, "0/0")
                            else:
                                recording_val = away_leader["recording_stats"].get(code, 0) or 0
                                calc_val = away_leader["calculated_stats"].get(code, 0) or 0
                                away_leader_stats[code] = str(recording_val + calc_val)                # Add the leader to the leaders list
                leaders.append({
                    "category": category_name,
                    "category_id": category.id,
                    "stats": [
                        {
                            "code": stat.code,
                            "name": stat.name,
                            "display_name": stat.display_name or stat.name,
                        } 
                        for stat in category_stats
                    ],                    "home_team": {
                        "player_id": home_leader["player_id"],
                        "player_name": home_leader["player_name"],
                        "short_name": home_leader["short_name"],
                        "jersey_number": home_leader["jersey_number"],
                        "team_abbreviation": self.game.home_team.abbreviation,
                        "profile": home_leader.get("profile_url"),
                        "stats": home_leader_stats
                    },
                    "away_team": {
                        "player_id": away_leader["player_id"],
                        "player_name": away_leader["player_name"],
                        "short_name": away_leader["short_name"],
                        "jersey_number": away_leader["jersey_number"],
                        "team_abbreviation": self.game.away_team.abbreviation,
                        "profile": away_leader.get("profile_url"),
                        "stats": away_leader_stats
                    }
                })
        
        return leaders

    def get_game_leaders(self):
        summary = self._build_initial_summary()
        self._populate_recording_stats(summary)  # First populate recording stats
        self._compute_formula_stats(summary)     # Then compute formula-based stats
        leaders = self._find_team_leaders(summary)
        
        return {
            "game_id": self.game.id,
            "home_team": {
                "team_id": self.game.home_team.id,
                "team_name": self.game.home_team.name,
                "team_abbreviation": self.game.home_team.abbreviation,
            },
            "away_team": {
                "team_id": self.game.away_team.id,
                "team_name": self.game.away_team.name,
                "team_abbreviation": self.game.away_team.abbreviation,
            },
            "leaders": leaders
        }