from collections import defaultdict
from django.db.models import Count
from games.models import Game, PlayerStat
from sports.models import Sport, SportStatType
from teams.models import Player


class BoxscoreService:
    def __init__(self, game_id):
        self.game = Game.objects.select_related("home_team", "away_team").get(pk=game_id)
        self.teams = [self.game.home_team, self.game.away_team]
        
        # Get ALL stats for this sport (for calculations)
        self.all_stats = SportStatType.objects.filter(
            sport=self.game.sport
        ).prefetch_related(
            'formula', 
            'formula__components',
            'formula__components__stat_type'
        )
        
        # Get stats marked for boxscore display
        self.boxscore_stats = self.all_stats.filter(is_boxscore=True)
        
        # Separate recording stats and formula stats
        self.recording_stats = self.all_stats.filter(is_record=True)
        self.formula_stats = self.all_stats.filter(formula__isnull=False)
        
        # Get codes for different stat types
        self.recording_abbrevs = list(self.recording_stats.values_list("code", flat=True))
        self.formula_abbrevs = list(self.formula_stats.values_list("code", flat=True))
        
        # Get scoring stats (stats that have point values)
        self.scoring_stats = SportStatType.objects.filter(
            sport=self.game.sport,
            is_record=True,
            point_value__gt=0
        )

    def _aggregate_recording_stats(self):
        filters = {
            "game": self.game,
            "stat_type__in": self.recording_stats,
        }
        
        # Only include period in grouping for set-based sports
        group_by = ["player_id", "player__team", "stat_type__code"]
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
                }
                
                player_summary = {
                    "player_id": player.user.id,
                    "player_name": player.user.get_full_name(),
                    "jersey_number": player.jersey_number,
                    "team_id": player.team.id,
                }
                
                # Only include periods for set-based sports
                if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                    player_summary["periods"] = {
                        p: {
                            "recording_stats": dict.fromkeys(self.recording_abbrevs, 0),
                            "calculated_stats": dict.fromkeys(self.formula_abbrevs, 0),
                            "ratio_stats": dict.fromkeys(self.formula_abbrevs, None),
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
            
            if pid not in summary:
                continue
                
            if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                per = rec["period"]
                if per <= self.game.current_period:
                    summary[pid]["periods"][per]["recording_stats"][abbr] = cnt
            else:
                summary[pid]["recording_stats"][abbr] = cnt

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
                'is_ratio': stat.formula.is_ratio and len(component_codes) == 2
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
            # Only use decimal_places from formula
            decimal_places = stat.formula.decimal_places
            
            for data in summary.values():
                if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                    for pd in data["periods"].values():
                        variables = {}
                        for code in component_codes:
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

    def _build_response(self, summary):
        # Use only boxscore stats for the response display
        stat_display_names = {
            stat.code: stat.display_name or stat.name
            for stat in self.boxscore_stats
        }
        
        # Create mapping of stat codes to point values for scoring calculation
        scoring_stat_points = {
            stat.code: stat.point_value
            for stat in self.scoring_stats
        }
        
        # Create a lookup for ratio stats and their components
        ratio_component_lookup = {}
        for stat in self.formula_stats.filter(formula__is_ratio=True):
            if stat.formula:
                components = stat.formula.components.all().order_by('order')
                if len(components) == 2:
                    makes_code = components[0].stat_type.code
                    attempts_code = components[1].stat_type.code
                    ratio_component_lookup[stat.code] = (makes_code, attempts_code)
        
        # Create a lookup for derived stats and their required components
        formula_component_map = {}
        for stat in self.formula_stats:
            if stat.formula and not stat.formula.is_ratio:
                components = list(stat.formula.components.all().order_by('order'))
                formula_component_map[stat.code] = [comp.stat_type.code for comp in components]
        
        # Organize players by team
        home_team_players = []
        away_team_players = []
        
        for pid, data in summary.items():
            response_entry = {
                "id": data["player_id"],
                "name": data["player_name"],
                "jersey_number": data["jersey_number"],
                "team_id": data["team_id"],
            }

            # For point-based sports, calculate total stats directly
            if self.game.sport.scoring_type != Sport.SCORING_TYPES.SETS:
                total_stats = {}
                total_points = 0
                combined_totals = defaultdict(lambda: {'value': 0, 'makes': 0, 'attempts': 0})
                
                # Calculate total points from ALL scoring stats, regardless of boxscore flag
                for code, value in data["recording_stats"].items():
                    if code in scoring_stat_points:
                        total_points += value * scoring_stat_points[code]
                        
                    # Only include in display stats if marked as boxscore
                    if code in stat_display_names:
                        display_name = stat_display_names[code]
                        total_stats[display_name] = value
                        combined_totals[display_name]['value'] += value
                
                # Process calculated stats and ratios - only boxscore stats for display
                for code, value in data["calculated_stats"].items():
                    if code in stat_display_names:
                        display_name = stat_display_names[code]
                        ratio_value = data["ratio_stats"].get(code)
                        
                        if ratio_value:
                            try:
                                made, attempted = map(int, ratio_value.split('/'))
                                combined_totals[display_name]['makes'] += made
                                combined_totals[display_name]['attempts'] += attempted
                                total_stats[display_name] = ratio_value
                            except (ValueError, AttributeError):
                                total_stats[display_name] = value
                                combined_totals[display_name]['value'] += value
                        else:
                            formula = next((stat.formula for stat in self.formula_stats if stat.code == code), None)
                            decimal_places = formula.decimal_places if formula else None
                            is_float = isinstance(value, float)
                            total_stats[display_name] = round(value, decimal_places) if (is_float and decimal_places is not None) else value
                            combined_totals[display_name]['value'] += value

                response_entry["total_stats"] = total_stats
                response_entry["total_points"] = total_points
                response_entry["stats"] = [
                    {
                        "name": stat,
                        "display_name": stat,
                        "value": value
                    }
                    for stat, value in total_stats.items()
                ]

            # For set-based sports, calculate period stats and totals
            else:
                # First collect all raw stats across periods
                recording_totals = defaultdict(int)
                ratio_makes_attempts = defaultdict(lambda: {'makes': 0, 'attempts': 0})
                formula_values = defaultdict(int)
                periods_out = []
                total_points = 0

                for period in range(1, self.game.current_period + 1):
                    period_data = data["periods"][period]
                    period_stats = {}
                    period_points = 0
                    
                    # Calculate period points from ALL scoring stats
                    for code, value in period_data["recording_stats"].items():
                        if code in scoring_stat_points and value:
                            period_points += value * scoring_stat_points[code]
                    
                        # Also collect raw stats for totals calculation
                        recording_totals[code] += value or 0
                    
                    # Process ratio stats for period
                    for code, ratio_value in period_data["ratio_stats"].items():
                        if code in ratio_component_lookup and ratio_value:
                            try:
                                made, attempted = map(int, ratio_value.split('/'))
                                ratio_makes_attempts[code]['makes'] += made
                                ratio_makes_attempts[code]['attempts'] += attempted
                            except (ValueError, AttributeError):
                                pass
                    
                    # Process formula values for period
                    for code, value in period_data["calculated_stats"].items():
                        if not code in ratio_component_lookup and value is not None:
                            formula_values[code] += value
                    
                    # Add recording stats to period display - only boxscore stats
                    for code, value in period_data["recording_stats"].items():
                        if code in stat_display_names:
                            display_name = stat_display_names[code]
                            period_stats[display_name] = value
                    
                    # Add calculated stats and ratios to period display - only boxscore stats
                    for code, value in period_data["calculated_stats"].items():
                        if code in stat_display_names:
                            display_name = stat_display_names[code]
                            ratio_value = period_data["ratio_stats"].get(code)
                            
                            if ratio_value:
                                period_stats[display_name] = ratio_value
                            else:
                                if isinstance(value, float):
                                    formula = next((stat.formula for stat in self.formula_stats if stat.code == code), None)
                                    decimal_places = formula.decimal_places if formula else None
                                    if decimal_places is not None:
                                        period_stats[display_name] = round(value, decimal_places)
                                    else:
                                        period_stats[display_name] = value
                                else:
                                    period_stats[display_name] = value
                    
                    periods_out.append({
                        "period": period,
                        "stats": period_stats,
                        "points": period_points
                    })
                    
                    # Add to total points
                    total_points += period_points

                # Now calculate the total stats correctly
                totals = {}
                
                # Add recording stats to totals - only boxscore stats
                for code, value in recording_totals.items():
                    if code in stat_display_names:
                        display_name = stat_display_names[code]
                        totals[display_name] = value
                
                # Add ratio stats to totals - only boxscore stats
                for code, components in ratio_component_lookup.items():
                    if code in stat_display_names:
                        display_name = stat_display_names[code]
                        makes = ratio_makes_attempts[code]['makes']
                        attempts = ratio_makes_attempts[code]['attempts']
                        if attempts > 0:
                            totals[display_name] = f"{makes}/{attempts}"
                
                # Calculate derived formulas for totals
                for stat in self.formula_stats:
                    if stat.is_boxscore and not stat.formula.is_ratio and stat.formula.expression:
                        code = stat.code
                        display_name = stat_display_names.get(code)
                        
                        if not display_name:
                            continue
                        
                        components = formula_component_map.get(code, [])
                        if not components:
                            continue
                        
                        variables = {}
                        all_components_found = True
                        
                        # Build variables for formula calculation
                        for comp_code in components:
                            if comp_code in recording_totals:
                                variables[comp_code] = recording_totals[comp_code]
                            elif comp_code in formula_values:
                                variables[comp_code] = formula_values[comp_code]
                            elif comp_code in ratio_component_lookup:
                                if comp_code in ratio_makes_attempts:
                                    variables[comp_code] = ratio_makes_attempts[comp_code]['makes']
                                else:
                                    variables[comp_code] = 0
                                    all_components_found = False
                            else:
                                variables[comp_code] = 0
                                all_components_found = False
                        
                        # Calculate formula result if we have all components
                        if all_components_found and variables:
                            try:
                                result = eval(stat.formula.expression, {}, variables)
                                if isinstance(result, float):
                                    decimal_places = stat.formula.decimal_places
                                    result = round(result, decimal_places)
                                totals[display_name] = result
                            except Exception as e:
                                totals[display_name] = 0

                response_entry["periods"] = periods_out
                response_entry["total_stats"] = totals
                response_entry["total_points"] = total_points
            
            # Add to appropriate team list
            if data["team_id"] == self.game.home_team.id:
                home_team_players.append(response_entry)
            else:
                away_team_players.append(response_entry)
        
        return {
            "home_team": {
                "team_id": self.game.home_team.id,
                "team_name": self.game.home_team.name,
                "players": home_team_players
            },
            "away_team": {
                "team_id": self.game.away_team.id,
                "team_name": self.game.away_team.name,
                "players": away_team_players
            }
        }
        
    def get_boxscore(self):
        summary = self._build_initial_summary()
        self._populate_recording_stats(summary)  # First populate recording stats
        self._compute_formula_stats(summary)     # Then compute formula-based stats
        return self._build_response(summary)
