from collections import defaultdict
from django.db.models import Count
from games.models import Game, PlayerStat
from sports.models import Sport, SportStatType


class TeamStatsSummaryService:
    def __init__(self, game_id):
        self.game = Game.objects.select_related("home_team", "away_team").get(pk=game_id)
        self.teams = [self.game.home_team, self.game.away_team]
        
        # Get ALL stats for this sport without filtering is_team_summary
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

    def _build_initial_summary(self):
        summary = {}
        for team in self.teams:
            stats_structure = {
                "recording_stats": dict.fromkeys(self.recording_abbrevs, 0),
                "calculated_stats": dict.fromkeys(self.formula_abbrevs, 0),
                "ratio_stats": dict.fromkeys(self.formula_abbrevs, None),
            }
            
            team_summary = {
                "team_id": team.id,
                "team_name": team.name,
            }
            
            # For point-scoring sports, store stats at the top level too
            if self.game.sport.scoring_type == Sport.SCORING_TYPES.POINTS:
                team_summary.update(stats_structure)
            
            # Initialize periods structure for all periods up to current
            team_summary["periods"] = {
                p: {
                    "recording_stats": dict.fromkeys(self.recording_abbrevs, 0),
                    "calculated_stats": dict.fromkeys(self.formula_abbrevs, 0),
                    "ratio_stats": dict.fromkeys(self.formula_abbrevs, None),
                }
                for p in range(1, self.game.current_period + 1)
            }
            
            summary[team.id] = team_summary
            
        return summary

    def _aggregate_recording_stats(self):
        # First sum up all recorded stats for each team, grouped by period and stat type
        team_stats = (
            PlayerStat.objects.filter(
                game=self.game, 
                stat_type__is_record=True  # Ensure we only get recorded stats
            )
            .values("player__team", "period", "stat_type__code")
            .annotate(total=Count("id"))
        )
        return team_stats

    def _populate_recording_stats(self, summary):
        # Get all recorded stats
        team_stats = self._aggregate_recording_stats()

        # Populate recording stats first
        for stat in team_stats:
            team_id = stat["player__team"]
            period = stat["period"]
            abbr = stat["stat_type__code"]
            total = stat["total"]

            if team_id in summary and period <= self.game.current_period:
                # Add to the recording stats total for this team and period
                summary[team_id]["periods"][period]["recording_stats"][abbr] = total
                
                # For points scoring type, also aggregate to the top level
                if self.game.sport.scoring_type == Sport.SCORING_TYPES.POINTS:
                    summary[team_id]["recording_stats"][abbr] += total

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
            # Only use decimal_places from formula
            decimal_places = stat.formula.decimal_places
            
            # Process per-period formula stats
            for team_data in summary.values():
                for period_data in team_data["periods"].values():
                    variables = {}
                    for code in component_codes:
                        # Get value from either recording or calculated stats
                        recording_val = period_data["recording_stats"].get(code, 0) or 0
                        calc_val = period_data["calculated_stats"].get(code, 0) or 0
                        variables[code] = recording_val + calc_val
                    
                    if is_ratio_stat:
                        made = variables[component_codes[0]]
                        attempted = variables[component_codes[1]]
                        period_data["calculated_stats"][stat.code] = None
                        period_data["ratio_stats"][stat.code] = f"{made}/{attempted}"
                    else:
                        if stat.formula.expression:
                            try:
                                result = eval(stat.formula.expression, {}, variables)
                                if isinstance(result, float):
                                    result = round(result, decimal_places)
                                period_data["calculated_stats"][stat.code] = result
                            except:
                                period_data["calculated_stats"][stat.code] = 0
                        else:
                            period_data["calculated_stats"][stat.code] = 0
                
                # For point scoring sports, also compute at the top level
                if self.game.sport.scoring_type == Sport.SCORING_TYPES.POINTS:
                    variables = {}
                    for code in component_codes:
                        # Get value from either recording or calculated stats
                        recording_val = team_data["recording_stats"].get(code, 0) or 0
                        calc_val = team_data["calculated_stats"].get(code, 0) or 0
                        variables[code] = recording_val + calc_val
                    
                    if is_ratio_stat:
                        made = variables[component_codes[0]]
                        attempted = variables[component_codes[1]]
                        team_data["calculated_stats"][stat.code] = None
                        team_data["ratio_stats"][stat.code] = f"{made}/{attempted}"
                    else:
                        if stat.formula.expression:
                            try:
                                result = eval(stat.formula.expression, {}, variables)
                                if isinstance(result, float):
                                    result = round(result, decimal_places)
                                team_data["calculated_stats"][stat.code] = result
                            except:
                                team_data["calculated_stats"][stat.code] = 0
                        else:
                            team_data["calculated_stats"][stat.code] = 0

    def _build_response(self, summary):
        # Get team summary stats for the response output
        team_summary_stats = self.all_stats.filter(is_team_summary=True).order_by('name')
        stat_display_names = {
            stat.code: stat.name
            for stat in team_summary_stats
        }
        
        # Create a lookup for stats that are part of ratios, including any dependency stats needed
        ratio_component_lookup = {}
        ratio_stats = self.formula_stats.filter(formula__is_ratio=True)
        for stat in ratio_stats:
            if stat.formula:
                components = stat.formula.components.all().order_by('order')
                if len(components) == 2:
                    makes_code = components[0].stat_type.code
                    attempts_code = components[1].stat_type.code
                    ratio_component_lookup[stat.code] = (makes_code, attempts_code)
        
        # Create a lookup for derived stats and their required components, regardless of team_summary flag
        formula_component_map = {}
        for stat in self.formula_stats:
            if stat.formula and not stat.formula.is_ratio:
                components = list(stat.formula.components.all().order_by('order'))
                formula_component_map[stat.code] = [comp.stat_type.code for comp in components]
        
        # Reverse mapping for formula code lookup
        display_name_to_code = {v: k for k, v in stat_display_names.items()}
        
        teams_data = {}
        for team_id, team_data in summary.items():
            total_stats = {}
            team_periods = []
            total_points = 0

            # Get period labels from game score_summary for set-based sports
            period_labels = {}
            if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                score_summary = self.game.score_summary or {}
                for period_data in score_summary.get('periods', []):
                    period_labels[period_data['period']] = period_data['label']

            # Points are calculated the same for both types of sports
            for period in range(1, self.game.current_period + 1):
                # Make sure period data exists
                if period not in team_data["periods"]:
                    continue
                    
                period_data = team_data["periods"][period]
                period_points = 0
                period_stats = {}

                # Calculate period points
                for stat in self.recording_stats.filter(point_value__gt=0):
                    stat_value = period_data["recording_stats"].get(stat.code, 0) or 0  # Ensure None becomes 0
                    if stat_value:
                        period_points += stat_value * stat.point_value
                
                # For set-based sports, process period stats
                if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                    # Process period stats for set-based sports
                    for code, value in period_data["recording_stats"].items():
                        if code in stat_display_names:
                            display_name = stat_display_names[code]
                            if isinstance(value, float):
                                formula = next((stat.formula for stat in self.formula_stats if stat.code == code), None)
                                decimal_places = formula.decimal_places if formula else None
                                if decimal_places is not None:
                                    period_stats[display_name] = round(value, decimal_places)
                                else:
                                    period_stats[display_name] = value
                            else:
                                period_stats[display_name] = value

                    for code, value in period_data["calculated_stats"].items():
                        if code in stat_display_names:
                            display_name = stat_display_names[code]
                            ratio_value = period_data["ratio_stats"].get(code)
                            if ratio_value:
                                period_stats[display_name] = ratio_value
                            else:
                                formula = next((stat.formula for stat in self.formula_stats if stat.code == code), None)
                                decimal_places = formula.decimal_places if formula else None
                                if isinstance(value, float) and decimal_places is not None:
                                    period_stats[display_name] = round(value, decimal_places)
                                else:
                                    period_stats[display_name] = value

                    # Get period label from our mapping
                    period_label = period_labels.get(period, period)

                    team_periods.append({
                        "period": period,
                        "label": f"Set {period_label}",
                        "points": period_points,
                        "stats": period_stats
                    })

                total_points += period_points

            # Calculate total stats differently based on sport type
            if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                # For set-based sports, we need to aggregate across periods
                # Track raw recording stats, ratio-based stats, and formula components separately
                
                # Collect ALL recording stats and calculated stats, even if not flagged as team_summary
                # This provides the raw data needed for formula calculations
                recording_totals = defaultdict(int)
                ratio_makes_attempts = defaultdict(lambda: {'makes': 0, 'attempts': 0})
                formula_values = defaultdict(int)
                
                # First pass: collect ALL stats across periods (not just team_summary ones)
                for period in range(1, self.game.current_period + 1):
                    # Skip if period data doesn't exist
                    if period not in team_data["periods"]:
                        continue
                        
                    period_data = team_data["periods"][period]
                    
                    # Collect ALL recording stats
                    for code, value in period_data["recording_stats"].items():
                        if value is not None:  # Skip None values
                            recording_totals[code] += value
                    
                    # Process ALL ratio stats
                    for code, value in period_data["calculated_stats"].items():
                        if code in ratio_component_lookup:
                            ratio_value = period_data["ratio_stats"].get(code)
                            if ratio_value:
                                try:
                                    makes, attempted = map(int, ratio_value.split('/'))
                                    ratio_makes_attempts[code]['makes'] += makes
                                    ratio_makes_attempts[code]['attempts'] += attempted
                                except (ValueError, AttributeError):
                                    pass
                        
                        # Store ALL calculated values (if not None)
                        if value is not None:  # Skip None values
                            formula_values[code] += value
                
                # Add team summary recording stats to total_stats
                for code, value in recording_totals.items():
                    if code in stat_display_names:
                        total_stats[stat_display_names[code]] = value
                
                # Add team summary ratio stats to total_stats
                for code, values in ratio_makes_attempts.items():
                    if code in stat_display_names:
                        makes = values['makes']
                        attempts = values['attempts']
                        total_stats[stat_display_names[code]] = f"{makes}/{attempts}"
                
                # Now calculate all derived formula stats that need to appear in team summary
                # This includes stats like "Hitting Percentage" even if their components aren't team_summary
                for stat in self.formula_stats:
                    # Only process derived stats (non-ratio) that are marked as team_summary
                    if not stat.formula or stat.formula.is_ratio or stat.code not in stat_display_names:
                        continue
                        
                    # Get component codes for this formula
                    component_codes = formula_component_map.get(stat.code, [])
                    if not component_codes or not stat.formula.expression:
                        continue
                    
                    # Build variables dict using ALL collected stats, not just team_summary ones
                    variables = {}
                    all_components_found = True
                    
                    # Look for each component in our collected data
                    for comp_code in component_codes:
                        # Check in recording stats first
                        if comp_code in recording_totals:
                            variables[comp_code] = recording_totals[comp_code]
                        
                        # Check if it's a ratio component
                        elif comp_code in ratio_component_lookup:
                            if comp_code in ratio_makes_attempts:
                                variables[comp_code] = ratio_makes_attempts[comp_code]['makes']
                            else:
                                all_components_found = False
                        
                        # Check in formula values
                        elif comp_code in formula_values:
                            variables[comp_code] = formula_values[comp_code]
                        
                        # If still not found, component is missing
                        else:
                            all_components_found = False
                    
                    # If we have all components, calculate the formula
                    if all_components_found and variables:
                        try:
                            # Add any ratio attempts as needed
                            for ratio_code, (makes_code, attempts_code) in ratio_component_lookup.items():
                                if makes_code in variables and attempts_code in stat.formula.expression:
                                    if ratio_code in ratio_makes_attempts:
                                        variables[attempts_code] = ratio_makes_attempts[ratio_code]['attempts']
                            
                            # Evaluate the formula
                            result = eval(stat.formula.expression, {}, variables)
                            if isinstance(result, float):
                                decimal_places = stat.formula.decimal_places
                                result = round(result, decimal_places)
                            
                            # Add to total stats
                            total_stats[stat_display_names[stat.code]] = result
                        except Exception as e:
                            # If formula evaluation fails, add 0
                            total_stats[stat_display_names[stat.code]] = 0
            else:
                # For point-scoring sports, use the already aggregated top-level stats
                for code, value in team_data["recording_stats"].items():
                    if code in stat_display_names and value is not None:  # Skip None values
                        display_name = stat_display_names[code]
                        total_stats[display_name] = value
                
                for code, value in team_data["calculated_stats"].items():
                    if code in stat_display_names:
                        display_name = stat_display_names[code]
                        ratio_value = team_data["ratio_stats"].get(code)
                        
                        if ratio_value:
                            total_stats[display_name] = ratio_value
                        elif value is not None:  # Skip None values
                            formula = next((stat.formula for stat in self.formula_stats if stat.code == code), None)
                            decimal_places = formula.decimal_places if formula else None
                            if isinstance(value, float) and decimal_places is not None:
                                total_stats[display_name] = round(value, decimal_places)
                            else:
                                total_stats[display_name] = value

            team_data_out = {
                "team_id": team_id,
                "team_name": team_data["team_name"],
                "total_points": total_points,
                "total_stats": total_stats
            }
            
            # Only include periods for set-based sports
            if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                team_data_out["periods"] = team_periods

            teams_data[team_id] = team_data_out

        return {
            "home_team": teams_data.get(self.game.home_team.id, {"team_id": self.game.home_team.id, "team_name": self.game.home_team.name, "total_points": 0, "total_stats": {}}),
            "away_team": teams_data.get(self.game.away_team.id, {"team_id": self.game.away_team.id, "team_name": self.game.away_team.name, "total_points": 0, "total_stats": {}}),
        }

    def get_summary(self):
        summary = self._build_initial_summary()
        self._populate_recording_stats(summary)  # First populate recording stats
        self._compute_formula_stats(summary)     # Then compute formula-based stats
        return self._build_response(summary)
    