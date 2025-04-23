from collections import defaultdict
from django.db.models import Count
from games.models import Game, PlayerStat, SportStatType
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
        return (
            PlayerStat.objects.filter(
                game=self.game,
                stat_type__in=self.base_stats,
                player__team__in=self.teams,
            )
            .values("player_id", "period", "stat_type__code")
            .annotate(count=Count("id"))
        )

    def _build_initial_summary(self):
        summary = {}
        for player in Player.objects.filter(team__in=self.teams).select_related("user"):
            summary[player.pk] = {
                "player_id": player.user.id,
                "player_name": player.user.get_full_name(),
                "jersey_number": player.jersey_number,
                "team_id": player.team.id,
                "periods": {
                    p: {
                        "base_stats": dict.fromkeys(self.base_abbrevs, 0),
                        "calculated_stats": dict.fromkeys(self.all_calc_abbrevs, 0),
                    }
                    for p in range(1, self.game.current_period + 1)
                },
            }
        return summary

    def _populate_base(self, summary):
        for rec in self._aggregate_base_stats():
            pid, per, abbr, cnt = (
                rec["player_id"],
                rec["period"],
                rec["stat_type__code"],
                rec["count"],
            )
            if pid in summary and per <= self.game.current_period:
                summary[pid]["periods"][per]["base_stats"][abbr] = cnt

    def _compute_formula_stats(self, summary):
        for stat in self.formula_stats:
            if not stat.formula:
                continue
                
            # Get component codes
            component_codes = [
                comp.stat_type.code 
                for comp in stat.formula.components.all()
            ]
            
            for data in summary.values():
                for pd in data["periods"].values():
                    # Prepare variables
                    variables = {
                        code: pd["base_stats"].get(code, 0) + pd["calculated_stats"].get(code, 0)
                        for code in component_codes
                    }
                    
                    # Evaluate formula
                    try:
                        result = eval(stat.formula.expression, {}, variables)
                        if isinstance(result, float):
                            result = round(result, 1)
                        pd["calculated_stats"][stat.code] = result
                    except:
                        pd["calculated_stats"][stat.code] = 0
                        
    def _build_response(self, summary):
        # Get all stats that should be displayed
        display_stats = self.all_stats.filter(is_metrics=True)
        
        response = []
        for data in summary.values():
            # Initialize containers
            stats_list = []
            total_stats = {}
            total_points = 0

            # Process each stat
            for stat in display_stats:
                stat_total = 0
                period_values = {}

                # Calculate across all periods
                for period in range(1, self.game.current_period + 1):
                    base_val = data["periods"][period]["base_stats"].get(stat.code, 0)
                    calc_val = data["periods"][period]["calculated_stats"].get(stat.code, 0)
                    period_value = base_val + calc_val
                    stat_total += period_value
                    period_values[period] = period_value

                    # Add to points total if this is a point-scoring stat
                    if stat.point_value:
                        total_points += period_value * stat.point_value

                # Add to stats list
                stats_list.append({
                    "name": stat.name,
                    "display_name": stat.display_name or stat.name,
                    "value": round(stat_total, 1) if isinstance(stat_total, float) else stat_total,
                    "period_values": period_values
                })

                # Add to total_stats
                total_stats[stat.display_name or stat.name] = round(stat_total, 1) if isinstance(stat_total, float) else stat_total

            response.append({
                "id": data["player_id"],
                "name": data["player_name"],
                "jersey_number": data["jersey_number"],
                "team_id": data["team_id"],
                "stats": stats_list,
                "total_points": total_points,
                "total_stats": total_stats
            })
            
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
                
            # Get component codes
            component_codes = [
                comp.stat_type.code 
                for comp in stat.formula.components.all()
            ]
            
            for team_data in summary.values():
                for period_data in team_data["periods"].values():
                    # Prepare variables
                    variables = {
                        code: period_data["base_stats"].get(code, 0) + 
                              period_data["calculated_stats"].get(code, 0)
                        for code in component_codes
                    }
                    
                    # Evaluate formula
                    try:
                        result = eval(stat.formula.expression, {}, variables)
                        if isinstance(result, float):
                            result = round(result, 1)
                        period_data["calculated_stats"][stat.code] = result
                    except:
                        period_data["calculated_stats"][stat.code] = 0

    def _build_response(self, summary):
        """Build final response with display names and combined stats"""
        # Get metric stats and create display name mapping
        metric_stats = self.all_stats.filter(is_metrics=True)
        stat_display_names = {
            stat.code: stat.display_name or stat.name
            for stat in metric_stats
        }
        
        response = {}
        for team_id, team_data in summary.items():
            combined_totals = defaultdict(lambda: {'value': 0, 'is_float': False})
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
                        combined_totals[display_name]['is_float'] = False
                
                # Add calculated stats
                for code, value in period_data["calculated_stats"].items():
                    if code in stat_display_names:
                        display_name = stat_display_names[code]
                        is_float = isinstance(value, float)
                        combined_stats[display_name] = round(value, 1) if is_float else value
                        # Update totals
                        combined_totals[display_name]['value'] += value
                        combined_totals[display_name]['is_float'] = is_float

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
            totals = {
                stat: round(value['value'], 1) if value['is_float'] else value['value']
                for stat, value in combined_totals.items()
            }

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
