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
        self.all_stats = SportStatType.objects.filter(
            sport=self.game.sport
        ).prefetch_related(
            'formula', 
            'formula__components',
            'formula__components__stat_type'
        )
        
        self.base_stats = self.all_stats.filter(formula__isnull=True, is_record=True)
        self.formula_stats = self.all_stats.filter(formula__isnull=False)
        
        # codes
        self.counter_abbrevs = set(self.all_stats.filter(is_counter=True).values_list("code", flat=True))
        self.base_abbrevs = list(self.base_stats.values_list("code", flat=True))
        self.formula_abbrevs = list(self.formula_stats.values_list("code", flat=True))
        self.all_calc_abbrevs = self.formula_abbrevs

    def _get_teams(self):
        if self.team_filter == "home_team":
            return [self.game.home_team]
        if self.team_filter == "away_team":
            return [self.game.away_team]
        return [self.game.home_team, self.game.away_team]

    def _aggregate_base_stats(self):
        filters = {
            "game": self.game,
            "stat_type__in": self.base_stats,
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
                "base_stats": dict.fromkeys(self.base_abbrevs, 0),
                "calculated_stats": dict.fromkeys(self.all_calc_abbrevs, 0),
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
                        "base_stats": dict.fromkeys(self.base_abbrevs, 0),
                        "calculated_stats": dict.fromkeys(self.all_calc_abbrevs, 0),
                        "ratio_stats": dict.fromkeys(self.formula_abbrevs, None),
                    }
                    for p in range(1, self.game.current_period + 1)
                }
            else:
                player_summary.update(stats_structure)
                
            summary[player.pk] = player_summary
        return summary

    def _populate_base(self, summary):
        for rec in self._aggregate_base_stats():
            pid = rec["player_id"]
            abbr = rec["stat_type__code"]
            cnt = rec["count"]
            
            if pid not in summary:
                continue
                
            if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                per = rec["period"]
                if per <= self.game.current_period:
                    summary[pid]["periods"][per]["base_stats"][abbr] = cnt
            else:
                summary[pid]["base_stats"][abbr] = cnt

    def _compute_formula_stats(self, summary):
        # First, build dependency graph
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
        
        # Process all stats
        for stat_code in dependency_graph:
            if not process_stat(stat_code):
                ordered_stats = [info['stat'] for info in dependency_graph.values()]
                break
        
        # Now process stats in the resolved order
        for stat in ordered_stats:
            components = stat.formula.components.all().order_by('order')
            component_codes = [comp.stat_type.code for comp in components]
            is_ratio_stat = stat.formula.is_ratio and len(component_codes) == 2
            decimal_places = stat.formula.decimal_places if stat.formula else 3
            
            for data in summary.values():
                if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                    for pd in data["periods"].values():
                        variables = {}
                        for code in component_codes:
                            base_val = pd["base_stats"].get(code, 0) or 0
                            calc_val = pd["calculated_stats"].get(code, 0) or 0
                            variables[code] = base_val + calc_val
                        
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
                        base_val = data["base_stats"].get(code, 0) or 0
                        calc_val = data["calculated_stats"].get(code, 0) or 0
                        variables[code] = base_val + calc_val
                    
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
        # Get all stats that should be displayed
        display_stats = self.all_stats.filter(is_player_summary=True)
        # Only counter stats with point_value > 0
        counter_stats = self.all_stats.filter(is_counter=True, point_value__gt=0)
        counter_stat_codes = set(counter_stats.values_list("code", flat=True))
        counter_stat_point_values = {stat.code: stat.point_value for stat in counter_stats}
        
        response = []
        for data in summary.values():
            # Initialize stats containers
            stats_list = []
            total_stats = {}
            total_points = 0
            period_points = {}

            # Calculate points for this player
            if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                for period in range(1, self.game.current_period + 1):
                    period_points[period] = 0
                    for code in counter_stat_codes:
                        base_val = data["periods"][period]["base_stats"].get(code, 0) or 0
                        calc_val = data["periods"][period]["calculated_stats"].get(code, 0) or 0
                        stat_total = base_val + calc_val
                        period_points[period] += stat_total * counter_stat_point_values[code]
            else:
                for code in counter_stat_codes:
                    base_val = data["base_stats"].get(code, 0) or 0
                    calc_val = data["calculated_stats"].get(code, 0) or 0
                    stat_total = base_val + calc_val
                    total_points += stat_total * counter_stat_point_values[code]

            # Process each stat
            for stat in display_stats:
                if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                    # For set-based sports, calculate totals from period values
                    stat_total = 0
                    period_values = {}
                    ratio_values = {}
                    
                    for period in range(1, self.game.current_period + 1):
                        base_val = data["periods"][period]["base_stats"].get(stat.code, 0) or 0
                        calc_val = data["periods"][period]["calculated_stats"].get(stat.code, 0) or 0
                        ratio_val = data["periods"][period]["ratio_stats"].get(stat.code)
                        
                        period_value = base_val + calc_val
                        stat_total += period_value
                        period_values[period] = period_value
                        if ratio_val:
                            ratio_values[period] = ratio_val
                else:
                    # For point-based sports, use aggregate values
                    base_val = data["base_stats"].get(stat.code, 0) or 0
                    calc_val = data["calculated_stats"].get(stat.code, 0) or 0
                    ratio_val = data["ratio_stats"].get(stat.code)
                    stat_total = base_val + calc_val
                    period_values = {}
                    ratio_values = {}

                stat_entry = {
                    "name": stat.name,
                    "display_name": stat.display_name or stat.name,
                    "value": round(stat_total, 3) if isinstance(stat_total, float) else stat_total,
                }

                # Add ratio if available
                if ratio_val:
                    stat_entry["value"] = ratio_val
                
                if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                    stat_entry["period_values"] = period_values
                    if ratio_values:
                        stat_entry["value"] = ratio_values
                
                stats_list.append(stat_entry)
                total_stats[stat.display_name or stat.name] = round(stat_total, 3) if isinstance(stat_total, float) else stat_total

            response_entry = {
                "id": data["player_id"],
                "name": data["player_name"],
                "jersey_number": data["jersey_number"],
                "team_id": data["team_id"],
                "stats": stats_list,
                "total_stats": total_stats
            }

            # Add points based on sport type
            if self.game.sport.scoring_type == Sport.SCORING_TYPES.SETS:
                response_entry["period_points"] = period_points
            else:
                response_entry["total_points"] = total_points
            
            response.append(response_entry)
            
        return response
    
    def get_summary(self):
        summary = self._build_initial_summary()
        self._populate_base(summary)
        self._compute_formula_stats(summary)
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
        self.all_stats = SportStatType.objects.filter(
            sport=self.game.sport
        ).prefetch_related(
            'formula', 
            'formula__components',
            'formula__components__stat_type'
        )
        
        self.base_stats = self.all_stats.filter(formula__isnull=True)
        self.formula_stats = self.all_stats.filter(formula__isnull=False)
        
        # codes
        self.counter_abbrevs = set(self.all_stats.filter(is_counter=True).values_list("code", flat=True))
        self.base_abbrevs = list(self.base_stats.values_list("code", flat=True))
        self.formula_abbrevs = list(self.formula_stats.values_list("code", flat=True))
        self.all_calc_abbrevs = self.formula_abbrevs

    def _aggregate_base_stats(self):
        return (
            PlayerStat.objects.filter(game=self.game, stat_type__in=self.base_stats)
            .values("player__team", "period", "stat_type__code")
            .annotate(total=Count("id"))
        )

    def _build_initial_summary(self):
        """Initialize all possible stats with zeros"""
        summary = {}
        for team in self.teams:
            summary[team.id] = {
                "team_id": team.id,
                "team_name": team.name,
                "periods": {
                    period: {
                        "base_stats": dict.fromkeys(self.base_abbrevs, 0),
                        "calculated_stats": dict.fromkeys(self.all_calc_abbrevs, 0),
                    }
                    for period in range(1, self.game.current_period + 1)
                },
            }
        return summary

    def _populate_base(self, summary):
        """Populate base stats from database records"""
        for rec in self._aggregate_base_stats():
            team_id = rec["player__team"]
            period = rec["period"]
            abbr = rec["stat_type__code"]
            count = rec["total"]

            if team_id in summary and period <= self.game.current_period:
                summary[team_id]["periods"][period]["base_stats"][abbr] += count

    def _compute_formula_stats(self, summary):
        """Calculate formula-based stats"""
        for stat in self.formula_stats:
            if not stat.formula:
                continue
                
            # Get component codes in order for ratio calculation
            components = stat.formula.components.all().order_by('order')
            component_codes = [comp.stat_type.code for comp in components]
            
            # First check if this is a ratio formula
            is_ratio_stat = stat.formula.is_ratio and len(component_codes) == 2
            
            for team_data in summary.values():
                for period_data in team_data["periods"].values():
                    # Prepare variables with null checks
                    variables = {
                        code: (period_data["base_stats"].get(code, 0) or 0) + 
                              (period_data["calculated_stats"].get(code, 0) or 0)
                        for code in component_codes
                    }
                    
                    if is_ratio_stat:
                        # For ratio stats, always store the ratio string, even for 0/0
                        made = variables[component_codes[0]]
                        attempted = variables[component_codes[1]]
                        result = round((made / attempted) * 100, 1) if attempted > 0 else 0
                        ratio_string = f"{made}/{attempted}"  # Always show the ratio
                        period_data["ratio_stats"] = period_data.get("ratio_stats", {})  # Initialize if doesn't exist
                        period_data["ratio_stats"][stat.code] = ratio_string
                        period_data["calculated_stats"][stat.code] = result
                    else:
                        # For regular formulas, evaluate the expression if it exists
                        if stat.formula.expression:
                            try:
                                result = eval(stat.formula.expression, {}, variables)
                                if isinstance(result, float):
                                    result = round(result, 1)
                                period_data["calculated_stats"][stat.code] = result
                            except Exception as e:
                                period_data["calculated_stats"][stat.code] = 0
                        else:
                            period_data["calculated_stats"][stat.code] = 0

    def _build_response(self, summary):
        """Build final response with display names and combined stats"""
        # Get metric stats and create display name mapping
        metric_stats = self.all_stats.filter(is_team_summary=True)
        stat_display_names = {
            stat.code: stat.display_name or stat.name
            for stat in metric_stats
        }
        
        response = {}
        for team_id, team_data in summary.items():
            combined_totals = defaultdict(lambda: {'value': 0, 'attempts': 0, 'made': 0})
            periods_out = []

            for period in range(1, self.game.current_period + 1):
                period_data = team_data["periods"][period]
                
                # Combine base and calculated stats
                combined_stats = {}
                
                # Add base stats
                for code, value in period_data["base_stats"].items():
                    if code in stat_display_names:
                        display_name = stat_display_names[code]
                        combined_stats[display_name] = value
                        # Update totals
                        combined_totals[display_name]['value'] += value
                
                # Add calculated stats and ratios
                for code, value in period_data["calculated_stats"].items():
                    if code in stat_display_names:
                        display_name = stat_display_names[code]
                        # Check if this is a ratio stat
                        if "ratio_stats" in period_data and code in period_data["ratio_stats"]:
                            combined_stats[display_name] = period_data["ratio_stats"][code]
                            # For ratio stats, split the ratio string to update totals
                            made, attempted = map(int, period_data["ratio_stats"][code].split('/'))
                            combined_totals[display_name]['made'] += made
                            combined_totals[display_name]['attempts'] += attempted
                        else:
                            is_float = isinstance(value, float)
                            combined_stats[display_name] = round(value, 1) if is_float else value
                            # Update regular totals
                            combined_totals[display_name]['value'] += value

                # Calculate points
                points = sum(
                    (period_data["base_stats"].get(s.code, 0) + 
                     period_data["calculated_stats"].get(s.code, 0))
                    * s.point_value
                    for s in self.all_stats
                    if s.point_value
                )

                periods_out.append({
                    "period": period,
                    "stats": combined_stats,
                    "points": points
                })

            # Prepare totals
            totals = {}
            for stat, data in combined_totals.items():
                if data['attempts'] > 0:  # This is a ratio stat
                    totals[stat] = f"{data['made']}/{data['attempts']}"
                else:  # Regular stat
                    totals[stat] = data['value']

            response[team_id] = {
                "team_id": team_data["team_id"],
                "team_name": team_data["team_name"],
                "periods": periods_out,
                "total_points": sum(p["points"] for p in periods_out),
                "total_stats": totals,
            }

        return {
            "home_team": response[self.game.home_team.id],
            "away_team": response[self.game.away_team.id],
        }

    def get_summary(self):
        """Main entry point"""
        summary = self._build_initial_summary()
        self._populate_base(summary)
        self._compute_formula_stats(summary)
        return self._build_response(summary)
