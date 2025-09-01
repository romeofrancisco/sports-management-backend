from collections import defaultdict
from django.db.models import Count, Sum, F, Q, Case, When, IntegerField
from django.db import connection
from games.models import Game, PlayerStat
from sports.models import Sport, SportStatType
from teams.models import Player
import logging

logger = logging.getLogger(__name__)

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

    def _aggregate_recording_stats(self, for_calculation=False):
        """
        Optimized method to aggregate player stats with efficient database queries
        - Uses database aggregation to minimize data transfer
        - Fetches only necessary fields
        """
        filters = {
            "game": self.game,
            "stat_type__in": self.recording_stats,
            "player__team__in": self.teams,
        }
        
        # Only include period in grouping for set-based sports
        group_by = ["player_id", "stat_type__code", "stat_type__point_value"]
        if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
            group_by.append("period")
        
        query = PlayerStat.objects.filter(**filters)
        
        # If this is for calculation only, optimize further by:
        # 1. Only selecting fields we need
        # 2. Using database aggregation more aggressively
        if for_calculation:
            # For calculation, we only need the counts, not full objects
            query = query.values(*group_by).annotate(count=Count("id", distinct=True))
        else:
            # For display, we want more data
            query = query.values(*group_by).annotate(count=Count("id"))
            
        # Remove any default ordering to improve performance
        query = query.order_by()
        
        return query
    
    def _aggregate_stats_with_raw_sql(self, for_calculation=False):
        """
        Ultra-optimized method that uses raw SQL for better performance with large datasets
        Only use this for very large player stat datasets (thousands of records)
        """
        # Determine if we need to filter by team
        team_filter = ""
        team_params = []
        
        if self.team_filter == "home_team":
            team_filter = "AND p.team_id = %s"
            team_params = [self.game.home_team_id]
        elif self.team_filter == "away_team":
            team_filter = "AND p.team_id = %s"
            team_params = [self.game.away_team_id]
        
        # For calculation, use a more optimized query that only gets what's needed
        if for_calculation:
            # Different SQL based on scoring type
            if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                sql = """
                SELECT 
                    ps.player_id, 
                    st.code as stat_type__code, 
                    ps.period,
                    COUNT(ps.id) as count
                FROM 
                    games_playerstat ps
                INNER JOIN 
                    sports_sportstattype st ON ps.stat_type_id = st.id
                INNER JOIN 
                    teams_player p ON ps.player_id = p.user_id
                WHERE 
                    ps.game_id = %s
                    AND st.is_record = TRUE
                    {}
                GROUP BY 
                    ps.player_id, st.code, ps.period
                """.format(team_filter)
                
                params = [self.game.id] + team_params
            else:
                sql = """
                SELECT 
                    ps.player_id, 
                    st.code as stat_type__code, 
                    COUNT(ps.id) as count
                FROM 
                    games_playerstat ps
                INNER JOIN 
                    sports_sportstattype st ON ps.stat_type_id = st.id
                INNER JOIN 
                    teams_player p ON ps.player_id = p.user_id
                WHERE 
                    ps.game_id = %s
                    AND st.is_record = TRUE
                    {}
                GROUP BY 
                    ps.player_id, st.code
                """.format(team_filter)
                
                params = [self.game.id] + team_params
        else:
            # More complete query for display purposes
            if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                sql = """
                SELECT 
                    ps.player_id, 
                    st.code as stat_type__code,
                    st.name as stat_name,
                    st.display_name as display_name,
                    ps.period,
                    COUNT(ps.id) as count
                FROM 
                    games_playerstat ps
                INNER JOIN 
                    sports_sportstattype st ON ps.stat_type_id = st.id
                INNER JOIN 
                    teams_player p ON ps.player_id = p.user_id
                WHERE 
                    ps.game_id = %s
                    AND st.is_record = TRUE
                    {}
                GROUP BY 
                    ps.player_id, st.code, st.name, st.display_name, ps.period
                """.format(team_filter)
                
                params = [self.game.id] + team_params
            else:
                sql = """
                SELECT 
                    ps.player_id, 
                    st.code as stat_type__code,
                    st.name as stat_name,
                    st.display_name as display_name,
                    COUNT(ps.id) as count
                FROM 
                    games_playerstat ps
                INNER JOIN 
                    sports_sportstattype st ON ps.stat_type_id = st.id
                INNER JOIN 
                    teams_player p ON ps.player_id = p.user_id
                WHERE 
                    ps.game_id = %s
                    AND st.is_record = TRUE
                    {}
                GROUP BY 
                    ps.player_id, st.code, st.name, st.display_name
                """.format(team_filter)
                
                params = [self.game.id] + team_params
        
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [col[0] for col in cursor.description]
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
        return results

    def _build_initial_summary(self, for_calculation=False):
        summary = {}
        
        # Optimize the player query with select_related
        player_query = Player.objects.filter(team__in=self.teams).select_related("user")
        
        for player in player_query:
            # For calculation mode, use a more minimal structure
            if for_calculation:
                stats_structure = {
                    "recording_stats": dict.fromkeys(self.recording_abbrevs, 0),
                    "calculated_stats": dict.fromkeys(self.formula_abbrevs, 0),
                    "ratio_stats": dict.fromkeys(self.formula_abbrevs, None),
                }
                
                player_summary = {
                    "player_id": player.user.id,
                    "team_id": player.team.id,
                }
            else:
                # Full structure for display
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

    def _populate_recording_stats(self, summary, for_calculation=False, use_raw_sql=False):
        # Determine which aggregation method to use based on the expected data size
        # For small to medium datasets, use the regular ORM method
        # For very large datasets (thousands of records), use raw SQL
        
        # Check if we expect a large dataset or user explicitly requests raw SQL
        if use_raw_sql:
            stats = self._aggregate_stats_with_raw_sql(for_calculation)
            logger.info(f"Using raw SQL aggregation for game {self.game.id}")
        else:
            # Count stats if we haven't been explicitly told to use raw SQL
            stat_count = PlayerStat.objects.filter(
                game=self.game,
                player__team__in=self.teams
            ).count()
            
            # If more than 1000 stats, use the more efficient raw SQL method
            if stat_count > 1000:
                stats = self._aggregate_stats_with_raw_sql(for_calculation)
                logger.info(f"Auto-switched to raw SQL for large dataset ({stat_count} stats) for game {self.game.id}")
            else:
                stats = self._aggregate_recording_stats(for_calculation)
                logger.info(f"Using ORM aggregation for game {self.game.id} ({stat_count} stats)")
        
        # Process the stats and store them in the summary
        for rec in stats:
            pid = rec["player_id"]
            abbr = rec["stat_type__code"]
            cnt = rec["count"]
            point_value = rec.get("stat_type__point_value", 0)
            
            if pid not in summary:
                continue
                
            if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                per = rec["period"]
                if per <= self.game.current_period:
                    summary[pid]["periods"][per]["recording_stats"][abbr] = cnt
                    # Store point value for later use in formulas
                    if "point_values" not in summary[pid]["periods"][per]:
                        summary[pid]["periods"][per]["point_values"] = {}
                    summary[pid]["periods"][per]["point_values"][abbr] = point_value
            else:
                summary[pid]["recording_stats"][abbr] = cnt
                # Store point value for later use in formulas
                if "point_values" not in summary[pid]:
                    summary[pid]["point_values"] = {}
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
                            if uses_point_value and "point_values" in pd and code in pd["point_values"]:
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
                                except Exception as e:
                                    pd["calculated_stats"][stat.code] = 0
                                    logger.debug(f"Error evaluating formula for {stat.code}: {str(e)}")
                            else:
                                pd["calculated_stats"][stat.code] = 0
                else:
                    variables = {}
                    for code in component_codes:
                        # Use point value instead of count if the formula requires it
                        if uses_point_value and "point_values" in data and code in data["point_values"]:
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
                            except Exception as e:
                                data["calculated_stats"][stat.code] = 0
                                logger.debug(f"Error evaluating formula for {stat.code}: {str(e)}")
                        else:
                            data["calculated_stats"][stat.code] = 0

    def _build_response(self, summary, for_calculation=False):
        # Only use player summary stats for the response (unless for calculation)
        if for_calculation:
            player_summary_stats = self.all_stats
        else:
            player_summary_stats = self.all_stats.filter(is_player_summary=True)
            
        stat_display_names = {
            stat.code: stat.display_name or stat.name
            for stat in player_summary_stats
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
        
        response = []
        for data in summary.values():
            # For calculation mode, use minimal structure
            if for_calculation:
                response_entry = {
                    "id": data["player_id"],
                    "team_id": data["team_id"],
                }
            else:
                # Full structure for display
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
                
                if not for_calculation:
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
                    # Initialize combined_stats and period_stats for this period
                    period_stats = {}
                    period_points = 0
                    
                    # Calculate period points from recording stats (but DON'T add to totals here)
                    for stat in self.recording_stats.filter(point_value__gt=0):
                        stat_value = period_data["recording_stats"].get(stat.code, 0)
                        if stat_value:
                            period_points += stat_value * stat.point_value
                    
                    # Collect all recording stats for period and totals (ONLY ONCE HERE)
                    for code, value in period_data["recording_stats"].items():
                        # Add to period stats display if in player summary
                        if code in stat_display_names:
                            display_name = stat_display_names[code]
                            period_stats[display_name] = value
                        
                        # Add to recording totals (this is the ONLY place we add to totals)
                        recording_totals[code] += value or 0
                    
                    # Process ratio stats for period
                    for code, ratio_value in period_data["ratio_stats"].items():
                        if code in ratio_component_lookup and ratio_value:
                            try:
                                made, attempted = map(int, ratio_value.split('/'))
                                ratio_makes_attempts[code]['makes'] += made
                                ratio_makes_attempts[code]['attempts'] += attempted
                                
                                # Add to period stats display if in player summary
                                if code in stat_display_names:
                                    display_name = stat_display_names[code]
                                    period_stats[display_name] = ratio_value
                            except (ValueError, AttributeError):
                                pass
                    
                    # Process formula values for period
                    for code, value in period_data["calculated_stats"].items():
                        if not code in ratio_component_lookup and value is not None:
                            # Add to period stats display if in player summary
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
                            
                            # DON'T collect formula values for totals - they should be recalculated
                            # formula_values[code] += value
                    
                    # Only add periods if not in calculation mode
                    if not for_calculation:
                        periods_out.append({
                            "period": period,
                            "stats": period_stats,
                            "points": period_points
                        })
                    
                    # Add to total points
                    total_points += period_points

                # Now calculate the total stats correctly
                totals = {}
                
                # Add recording stats to totals - only player summary stats
                for code, value in recording_totals.items():
                    if code in stat_display_names:
                        display_name = stat_display_names[code]
                        totals[display_name] = value
                
                # Add ratio stats to totals - only player summary stats
                for code, components in ratio_component_lookup.items():
                    if code in stat_display_names:
                        display_name = stat_display_names[code]
                        makes = ratio_makes_attempts[code]['makes']
                        attempts = ratio_makes_attempts[code]['attempts']
                        # Always include ratio stats, even if attempts is 0
                        totals[display_name] = f"{makes}/{attempts}"
                
                # Calculate derived formulas for totals
                for stat in self.formula_stats:
                    if (for_calculation or stat.is_player_summary) and not stat.formula.is_ratio and stat.formula.expression:
                        code = stat.code
                        display_name = stat_display_names.get(code)
                        
                        if not display_name:
                            continue
                        
                        components = stat.formula.components.all().order_by('order')
                        component_codes = [comp.stat_type.code for comp in components]
                        
                        if not component_codes:
                            continue
                        
                        variables = {}
                        all_components_found = True
                        
                        # Build variables for formula calculation using TOTAL recording stats
                        # NOT the accumulated formula values from periods
                        for comp_code in component_codes:
                            if comp_code in recording_totals:
                                # Use total recording stats directly
                                if stat.formula.uses_point_value:
                                    # Get point value from any period that has it
                                    point_value = 0
                                    for period_data in data["periods"].values():
                                        if "point_values" in period_data and comp_code in period_data["point_values"]:
                                            point_value = period_data["point_values"][comp_code]
                                            break
                                    variables[comp_code] = recording_totals[comp_code] * point_value
                                else:
                                    variables[comp_code] = recording_totals[comp_code]
                            elif comp_code in ratio_makes_attempts:
                                # For ratio components, use the makes value
                                variables[comp_code] = ratio_makes_attempts[comp_code]['makes']
                            else:
                                # Check if this component is another calculated stat that we need to compute
                                # Look for its formula and calculate it with totals
                                comp_stat = next((s for s in self.formula_stats if s.code == comp_code), None)
                                if comp_stat and comp_stat.formula and not comp_stat.formula.is_ratio:
                                    # Recursively calculate this component using totals
                                    comp_components = comp_stat.formula.components.all().order_by('order')
                                    comp_variables = {}
                                    for comp_comp in comp_components:
                                        comp_comp_code = comp_comp.stat_type.code
                                        if comp_comp_code in recording_totals:
                                            if comp_stat.formula.uses_point_value:
                                                point_value = 0
                                                for period_data in data["periods"].values():
                                                    if "point_values" in period_data and comp_comp_code in period_data["point_values"]:
                                                        point_value = period_data["point_values"][comp_comp_code]
                                                        break
                                                comp_variables[comp_comp_code] = recording_totals[comp_comp_code] * point_value
                                            else:
                                                comp_variables[comp_comp_code] = recording_totals[comp_comp_code]
                                        elif comp_comp_code in ratio_makes_attempts:
                                            comp_variables[comp_comp_code] = ratio_makes_attempts[comp_comp_code]['makes']
                                        else:
                                            comp_variables[comp_comp_code] = 0
                                    
                                    if comp_stat.formula.expression and comp_variables:
                                        try:
                                            comp_result = eval(comp_stat.formula.expression, {}, comp_variables)
                                            variables[comp_code] = comp_result
                                        except Exception:
                                            variables[comp_code] = 0
                                            all_components_found = False
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
                                logger.debug(f"Error calculating formula for {code}: {str(e)}")

                response_entry["total_stats"] = totals
                response_entry["total_points"] = total_points
                
                # Only include periods if not in calculation mode
                if not for_calculation:
                    response_entry["periods"] = periods_out
                    
                    # Build period values for each stat
                    period_values_by_stat = {}
                    for period_data in periods_out:
                        period_num = period_data["period"]
                        for stat_name, value in period_data["stats"].items():
                            if stat_name not in period_values_by_stat:
                                period_values_by_stat[stat_name] = {}
                            period_values_by_stat[stat_name][str(period_num)] = value
                    
                    # Add stats field for frontend compatibility
                    response_entry["stats"] = [
                        {
                            "name": stat_name,
                            "display_name": stat_name,
                            "value": value,
                            "period_values": period_values_by_stat.get(stat_name, {})
                        }
                        for stat_name, value in totals.items()
                    ]

            response.append(response_entry)
            
        return response

    def get_summary(self, for_calculation=False, use_raw_sql=False):
        """
        Get player stats summary with optimization flags
        
        Args:
            for_calculation (bool): If True, optimize for calculation by returning minimal data
            use_raw_sql (bool): If True, always use raw SQL for maximum performance
            
        Returns:
            List of player stats summaries
        """
        summary = self._build_initial_summary(for_calculation)
        self._populate_recording_stats(summary, for_calculation, use_raw_sql)
        self._compute_formula_stats(summary)
        return self._build_response(summary, for_calculation)
