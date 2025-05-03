from collections import defaultdict
from django.db.models import Count
from games.models import Game, PlayerStat
from sports.models import Sport, SportStatType
from teams.models import Player
from django.db import transaction
from rest_framework.exceptions import ValidationError


class PlayerStatsSummaryService:
    def __init__(self, game_id, team_filter=None):
        self.game = Game.objects.select_related("home_team", "away_team").get(pk=game_id)
        self.team_filter = team_filter
        self.teams = self._get_teams()
        
        # Get all stats for this sport
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

    def _get_teams(self):
        if self.team_filter == "home_team":
            return [self.game.home_team]
        if self.team_filter == "away_team":
            return [self.game.away_team]
        return [self.game.home_team, self.game.away_team]

    def _aggregate_recording_stats(self):
        filters = {
            "game": self.game,
            "stat_type__in": self.recording_stats,
            "player__team__in": self.teams,
        }
        
        # Only include period in grouping for set-based sports
        group_by = ["player_id", "stat_type__code"]
        if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
            group_by.append("period")
            
        return (
            PlayerStat.objects.filter(**filters)
            .values(*group_by)
            .annotate(count=Count("id"))
        )

    def _build_initial_summary(self):
        summary = {}
        for player in Player.objects.filter(team__in=self.teams).select_related("user"):
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
        # Only use player summary stats for the response
        player_summary_stats = self.all_stats.filter(is_player_summary=True)
        stat_display_names = {
            stat.code: stat.display_name or stat.name
            for stat in player_summary_stats
        }
        
        response = []
        for data in summary.values():
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
                
                # Process recording stats - only player summary stats
                for code, value in data["recording_stats"].items():
                    if code in stat_display_names:  # This implicitly filters for player summary stats
                        display_name = stat_display_names[code]
                        total_stats[display_name] = value
                        combined_totals[display_name]['value'] += value
                        
                        # Add to points if it's a scoring stat
                        if self.recording_stats.filter(code=code, point_value__gt=0, is_player_summary=True).exists():
                            total_points += value * self.recording_stats.get(code=code).point_value
                
                # Process calculated stats and ratios - only player summary stats
                for code, value in data["calculated_stats"].items():
                    if code in stat_display_names:  # This implicitly filters for player summary stats
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
                combined_totals = defaultdict(lambda: {'value': 0, 'makes': 0, 'attempts': 0})
                periods_out = []

                for period in range(1, self.game.current_period + 1):
                    period_data = data["periods"][period]
                    # Initialize combined_stats and period_stats for this period
                    combined_stats = {}
                    period_stats = {}
                    period_points = 0
                    
                    # Calculate period points from recording stats
                    for stat in self.recording_stats.filter(point_value__gt=0):
                        stat_value = period_data["recording_stats"].get(stat.code, 0)
                        if stat_value:
                            period_points += stat_value * stat.point_value
                    
                    # Add recording stats - only player summary stats
                    for code, value in period_data["recording_stats"].items():
                        if code in stat_display_names:  # This implicitly filters for player summary stats
                            display_name = stat_display_names[code]
                            formula = next((stat.formula for stat in self.formula_stats if stat.code == code), None)
                            decimal_places = formula.decimal_places if formula else None
                            if isinstance(value, float):
                                if decimal_places is not None:
                                    period_stats[display_name] = round(value, decimal_places)
                                else:
                                    period_stats[display_name] = value
                            else:
                                period_stats[display_name] = value
                            combined_totals[display_name]['value'] += value

                            # Add to points if it's a scoring stat
                            if self.recording_stats.filter(code=code, point_value__gt=0, is_player_summary=True).exists():
                                period_points += value * self.recording_stats.get(code=code).point_value
                    
                    # Add calculated stats and ratios - only player summary stats
                    for code, value in period_data["calculated_stats"].items():
                        if code in stat_display_names:  # This implicitly filters for player summary stats
                            display_name = stat_display_names[code]
                            ratio_value = period_data["ratio_stats"].get(code)
                            
                            if ratio_value:
                                period_stats[display_name] = ratio_value
                                try:
                                    made, attempted = map(int, ratio_value.split('/'))
                                    combined_totals[display_name]['makes'] += made
                                    combined_totals[display_name]['attempts'] += attempted
                                except (ValueError, AttributeError):
                                    period_stats[display_name] = value
                                    combined_totals[display_name]['value'] += value
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
                                combined_totals[display_name]['value'] += value
                    
                    periods_out.append({
                        "period": period,
                        "stats": period_stats,
                        "points": period_points
                    })

                # Prepare totals
                totals = {}
                for stat, stat_data in combined_totals.items():
                    if stat_data['attempts'] > 0:  # This is a ratio stat
                        totals[stat] = f"{stat_data['makes']}/{stat_data['attempts']}"
                    else:  # Regular stat
                        totals[stat] = stat_data['value']

                response_entry["periods"] = periods_out
                response_entry["total_stats"] = totals
                response_entry["total_points"] = sum(p["points"] for p in periods_out)

            response.append(response_entry)
            
        return response

    def get_summary(self):
        summary = self._build_initial_summary()
        self._populate_recording_stats(summary)  # First populate recording stats
        self._compute_formula_stats(summary)     # Then compute formula-based stats
        return self._build_response(summary)

class RecordingService:
    def __init__(self, validated_data):
        self.player = validated_data["player"]
        self.game = validated_data["game"]
        self.stat_type = validated_data["stat_type"]

    def validate(self):
        if self.game.status != Game.Status.IN_PROGRESS:
            raise ValidationError({"game": "Game is not in progress"})

    @transaction.atomic
    def record(self):
        # create the main stat
        stat = PlayerStat.objects.create(
            player=self.player,
            game=self.game,
            stat_type=self.stat_type,
            period=self.game.current_period,
        )

        # bump the game’s score aggregates
        self.game.update_scores()

        return stat

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
