from collections import defaultdict
from django.db.models import Count
from games.models import Game, PlayerStat
from sports.models import Sport, SportStatType


class TeamStatsComparisonService:
    def __init__(self, game_id):
        self.game = Game.objects.select_related("home_team", "away_team").get(pk=game_id)
        self.teams = [self.game.home_team, self.game.away_team]
        
        # Get all stats for this sport without filtering
        self.all_stats = SportStatType.objects.filter(
            sport=self.game.sport
        ).prefetch_related(
            'formula', 
            'formula__components',
            'formula__components__stat_type'
        )
        
        # Separate recording stats and formula stats
        self.recording_stats = self.all_stats.filter(is_record=True)
        # Exclude stats with ratio formulas
        self.formula_stats = self.all_stats.filter(formula__isnull=False, formula__is_ratio=False)
        
        # Get codes for different stat types
        self.recording_abbrevs = list(self.recording_stats.values_list("code", flat=True))
        self.formula_abbrevs = list(self.formula_stats.values_list("code", flat=True))
        
        # Get ratio stats separately (needed for calculations but won't be displayed)
        self.ratio_stats = self.all_stats.filter(formula__isnull=False, formula__is_ratio=True)
        self.ratio_abbrevs = list(self.ratio_stats.values_list("code", flat=True))

    def _build_initial_summary(self):
        summary = {}
        for team in self.teams:
            # Create structures for all stat types including ratio stats
            all_formula_abbrevs = self.formula_abbrevs + self.ratio_abbrevs
            
            stats_structure = {
                "recording_stats": dict.fromkeys(self.recording_abbrevs, 0),
                "calculated_stats": dict.fromkeys(all_formula_abbrevs, 0),
                "ratio_stats": dict.fromkeys(all_formula_abbrevs, None),
            }
            
            team_summary = {
                "team_id": team.id,
                "team_name": team.name,
                "abbreviation": team.abbreviation,
            }
            
            # Initialize periods structure for all periods up to current
            if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                team_summary["periods"] = {
                    p: {
                        "recording_stats": dict.fromkeys(self.recording_abbrevs, 0),
                        "calculated_stats": dict.fromkeys(all_formula_abbrevs, 0),
                        "ratio_stats": dict.fromkeys(all_formula_abbrevs, None),
                    }
                    for p in range(1, self.game.current_period + 1)
                }
            else:
                team_summary.update(stats_structure)
            
            summary[team.id] = team_summary
            
        return summary

    def _aggregate_recording_stats(self):
        # Sum up all recorded stats for each team, grouped by period and stat type
        team_stats = (
            PlayerStat.objects.filter(
                game=self.game, 
                stat_type__is_record=True,
            )
            .values("player__team", "period", "stat_type__code")
            .annotate(total=Count("id"))
        )
        return team_stats

    def _populate_recording_stats(self, summary):
        # Get all recorded stats
        team_stats = self._aggregate_recording_stats()

        # Populate recording stats
        for stat in team_stats:
            team_id = stat["player__team"]
            period = stat["period"]
            abbr = stat["stat_type__code"]
            total = stat["total"]

            if team_id in summary:
                if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS and period <= self.game.current_period:
                    # Add to the recording stats total for this team and period
                    summary[team_id]["periods"][period]["recording_stats"][abbr] = total
                elif self.game.sport.scoring_type != Sport.SCORING_TYPES.SETS:
                    # For point-based sports, add directly to team stats
                    summary[team_id]["recording_stats"][abbr] = total

    def _compute_formula_stats(self, summary):
        # Build dependency graph for proper calculation order
        # Include ratio stats for calculations even though they won't be displayed
        all_formula_stats = list(self.formula_stats) + list(self.ratio_stats)
        
        dependency_graph = {}
        for stat in all_formula_stats:
            if not stat.formula:
                continue
                
            components = stat.formula.components.all().order_by('order')
            component_codes = [comp.stat_type.code for comp in components]
            dependency_graph[stat.code] = {
                'stat': stat,
                'dependencies': set(component_codes),
                'is_ratio': stat.formula.is_ratio and len(component_codes) == 2
            }
        
        # Get stats in correct processing order
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
            decimal_places = stat.formula.decimal_places
            
            if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                # Calculate for set-based sports by period
                for team_data in summary.values():
                    for period_data in team_data["periods"].values():
                        variables = {}
                        for code in component_codes:
                            # Get value from either recording or calculated stats
                            recording_val = period_data["recording_stats"].get(code, 0) or 0
                            calc_val = period_data["calculated_stats"].get(code, 0) or 0
                            variables[code] = recording_val + calc_val
                        
                        # Handle ratio stats differently
                        if is_ratio_stat:
                            made = variables[component_codes[0]]
                            attempted = variables[component_codes[1]]
                            period_data["calculated_stats"][stat.code] = None
                            period_data["ratio_stats"][stat.code] = f"{made}/{attempted}"
                        else:
                            # Calculate the formula result
                            if stat.formula.expression:
                                try:
                                    result = eval(stat.formula.expression, {}, variables)
                                    if isinstance(result, float):
                                        result = round(result, decimal_places)
                                    period_data["calculated_stats"][stat.code] = result
                                except Exception as e:
                                    period_data["calculated_stats"][stat.code] = 0
                            else:
                                period_data["calculated_stats"][stat.code] = 0
            else:
                # Calculate for point-based sports directly
                for team_data in summary.values():
                    variables = {}
                    for code in component_codes:
                        recording_val = team_data["recording_stats"].get(code, 0) or 0
                        calc_val = team_data["calculated_stats"].get(code, 0) or 0
                        variables[code] = recording_val + calc_val
                    
                    # Handle ratio stats differently
                    if is_ratio_stat:
                        made = variables[component_codes[0]]
                        attempted = variables[component_codes[1]]
                        team_data["calculated_stats"][stat.code] = None
                        team_data["ratio_stats"][stat.code] = f"{made}/{attempted}"
                    else:
                        # Calculate the formula result
                        if stat.formula.expression:
                            try:
                                result = eval(stat.formula.expression, {}, variables)
                                if isinstance(result, float):
                                    result = round(result, decimal_places)
                                team_data["calculated_stats"][stat.code] = result
                            except Exception as e:
                                team_data["calculated_stats"][stat.code] = 0
                        else:
                            team_data["calculated_stats"][stat.code] = 0

    def _build_response(self, summary):
        # Get stats marked for team comparison instead of team summary
        team_comparison_stats = self.all_stats.filter(is_team_comparison=True)
        stat_display_names = {
            stat.code: stat.name
            for stat in team_comparison_stats
        }
        
        # Create lookups for formula components and ratio stats
        ratio_component_lookup = {}
        for stat in self.ratio_stats:
            if stat.formula:
                components = stat.formula.components.all().order_by('order')
                if len(components) == 2:
                    makes_code = components[0].stat_type.code
                    attempts_code = components[1].stat_type.code
                    ratio_component_lookup[stat.code] = (makes_code, attempts_code)
        
        formula_component_map = {}
        for stat in self.formula_stats:
            if stat.formula:
                components = list(stat.formula.components.all().order_by('order'))
                formula_component_map[stat.code] = [comp.stat_type.code for comp in components]
        
        # Process stats for comparison format
        comparison_stats = []
        
        # Get data for home and away teams
        home_team_data = summary[self.game.home_team.id]
        away_team_data = summary[self.game.away_team.id]
        
        # Handle set-based sports
        if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
            # Track raw recording stats and formula components separately
            home_recording_totals = defaultdict(int)
            away_recording_totals = defaultdict(int)
            home_ratio_makes_attempts = defaultdict(lambda: {'makes': 0, 'attempts': 0})
            away_ratio_makes_attempts = defaultdict(lambda: {'makes': 0, 'attempts': 0})
            home_formula_values = defaultdict(int)
            away_formula_values = defaultdict(int)
            
            # First pass: collect stats across periods
            for period in range(1, self.game.current_period + 1):
                # Collect recording stats
                for code in self.recording_abbrevs:
                    home_recording_totals[code] += home_team_data["periods"][period]["recording_stats"].get(code, 0) or 0
                    away_recording_totals[code] += away_team_data["periods"][period]["recording_stats"].get(code, 0) or 0
                
                # Process ratio stats (needed for calculations)
                for code in self.ratio_abbrevs:
                    if code in ratio_component_lookup:
                        home_ratio_value = home_team_data["periods"][period]["ratio_stats"].get(code)
                        away_ratio_value = away_team_data["periods"][period]["ratio_stats"].get(code)
                        
                        if home_ratio_value:
                            try:
                                makes, attempts = map(int, home_ratio_value.split('/'))
                                home_ratio_makes_attempts[code]['makes'] += makes
                                home_ratio_makes_attempts[code]['attempts'] += attempts
                            except (ValueError, AttributeError):
                                pass
                        
                        if away_ratio_value:
                            try:
                                makes, attempts = map(int, away_ratio_value.split('/'))
                                away_ratio_makes_attempts[code]['makes'] += makes
                                away_ratio_makes_attempts[code]['attempts'] += attempts
                            except (ValueError, AttributeError):
                                pass
                
                # Regular calculated stats
                for code in self.formula_abbrevs:
                    home_value = home_team_data["periods"][period]["calculated_stats"].get(code, 0) or 0
                    away_value = away_team_data["periods"][period]["calculated_stats"].get(code, 0) or 0
                    home_formula_values[code] += home_value
                    away_formula_values[code] += away_value
            
            # Now calculate the formula stats that need to appear in team comparison
            home_final_values = {}
            away_final_values = {}
            
            # First add the recording stats
            for stat in self.recording_stats.filter(is_team_comparison=True):
                code = stat.code
                name = stat.name
                home_final_values[name] = home_recording_totals.get(code, 0)
                away_final_values[name] = away_recording_totals.get(code, 0)
            
            # Add formula stats (non-ratio only)
            for stat in self.formula_stats:
                if not stat.is_team_comparison:
                    continue
                
                code = stat.code
                name = stat.name
                
                # For normal formula stats, recalculate using the aggregated values
                if stat.formula and stat.formula.expression:
                    components = formula_component_map.get(code, [])
                    if components:
                        # Build variables for home team
                        home_variables = {}
                        for comp_code in components:
                            if comp_code in home_recording_totals:
                                home_variables[comp_code] = home_recording_totals[comp_code]
                            elif comp_code in home_ratio_makes_attempts:
                                # Use the "makes" for the component
                                home_variables[comp_code] = home_ratio_makes_attempts[comp_code]['makes']
                                
                                # If this is an "attempts" component, add it too
                                for ratio_code, (makes_code, attempts_code) in ratio_component_lookup.items():
                                    if comp_code == attempts_code and makes_code in home_variables:
                                        home_variables[attempts_code] = home_ratio_makes_attempts[ratio_code]['attempts']
                            elif comp_code in home_formula_values:
                                home_variables[comp_code] = home_formula_values[comp_code]
                        
                        # Calculate home formula result
                        decimal_places = stat.formula.decimal_places
                        try:
                            if home_variables:
                                home_result = eval(stat.formula.expression, {}, home_variables)
                                if isinstance(home_result, float):
                                    home_result = round(home_result, decimal_places)
                                home_final_values[name] = home_result
                        except Exception as e:
                            # If formula evaluation fails, use 0
                            home_final_values[name] = 0
                        
                        # Build variables for away team
                        away_variables = {}
                        for comp_code in components:
                            if comp_code in away_recording_totals:
                                away_variables[comp_code] = away_recording_totals[comp_code]
                            elif comp_code in away_ratio_makes_attempts:
                                # Use the "makes" for the component
                                away_variables[comp_code] = away_ratio_makes_attempts[comp_code]['makes']
                                
                                # If this is an "attempts" component, add it too
                                for ratio_code, (makes_code, attempts_code) in ratio_component_lookup.items():
                                    if comp_code == attempts_code and makes_code in away_variables:
                                        away_variables[attempts_code] = away_ratio_makes_attempts[ratio_code]['attempts']
                            elif comp_code in away_formula_values:
                                away_variables[comp_code] = away_formula_values[comp_code]
                        
                        # Calculate away formula result
                        try:
                            if away_variables:
                                away_result = eval(stat.formula.expression, {}, away_variables)
                                if isinstance(away_result, float):
                                    away_result = round(away_result, decimal_places)
                                away_final_values[name] = away_result
                        except Exception as e:
                            # If formula evaluation fails, use 0
                            away_final_values[name] = 0
                    else:
                        # If no components found, use the accumulated value
                        home_final_values[name] = home_formula_values.get(code, 0)
                        away_final_values[name] = away_formula_values.get(code, 0)
            
            # Build the comparison stats list
            for name in set(home_final_values.keys()) | set(away_final_values.keys()):
                home_value = home_final_values.get(name, 0)
                away_value = away_final_values.get(name, 0)
                
                if home_value > 0 or away_value > 0:  # Only include stats where at least one team has a value
                    comparison_stats.append({
                        "label": name,
                        "home_value": home_value,
                        "away_value": away_value,
                    })
        else:
            # Handle point-based sports (non-set-based)
            
            # Add recording stats - only include team_comparison stats
            for stat in self.recording_stats.filter(is_team_comparison=True):
                code = stat.code
                name = stat.name
                home_value = home_team_data["recording_stats"].get(code, 0)
                away_value = away_team_data["recording_stats"].get(code, 0)
                
                comparison_stats.append({
                    "label": name,
                    "home_value": home_value,
                    "away_value": away_value,
                })
            
            # Add formula stats - only non-ratio stats
            for stat in self.formula_stats:
                if stat.is_team_comparison:
                    code = stat.code
                    name = stat.name
                    home_value = home_team_data["calculated_stats"].get(code, 0)
                    away_value = away_team_data["calculated_stats"].get(code, 0)
                    
                    comparison_stats.append({
                        "label": name,
                        "home_value": home_value,
                        "away_value": away_value,
                    })
        
        # Sort by stat label
        comparison_stats.sort(key=lambda x: x["label"])
        
        # Filter out stats where both values are zero to avoid clutter
        comparison_stats = [stat for stat in comparison_stats if stat["home_value"] > 0 or stat["away_value"] > 0]
        
        return {
            "home_team": {
                "id": self.game.home_team.id,
                "name": self.game.home_team.name,
                "abbreviation": self.game.home_team.abbreviation
            },
            "away_team": {
                "id": self.game.away_team.id,
                "name": self.game.away_team.name,
                "abbreviation": self.game.away_team.abbreviation
            },
            "comparison_stats": comparison_stats
        }

    def get_comparison(self):
        summary = self._build_initial_summary()
        self._populate_recording_stats(summary)
        self._compute_formula_stats(summary)
        return self._build_response(summary)
