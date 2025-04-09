from collections import defaultdict
from django.db.models import Count
from games.models import Game, PlayerStat, SportStatType
from teams.models import Player
from django.db import transaction
from rest_framework.exceptions import ValidationError


class PlayerStatsSummaryService:
    def __init__(self, game_id, team_filter=None):
        self.game = Game.objects.select_related("home_team", "away_team").get(
            pk=game_id
        )
        self.team_filter = team_filter
        self.teams = self._get_teams()
        self.all_stats = SportStatType.objects.filter(sport=self.game.sport)
        self.base_stats = self.all_stats.filter(composite_stats__isnull=True)
        self.sum_composites = self.all_stats.filter(
            composite_stats__isnull=False, calculation_type="sum"
        ).prefetch_related("composite_stats")
        self.pct_composites = self.all_stats.filter(
            composite_stats__isnull=False, calculation_type="percentage"
        ).prefetch_related("composite_stats")

        # abbreviations
        self.counter_abbrevs = set(
            self.all_stats.filter(is_counter=True, calculation_type="none").values_list(
                "abbreviation", flat=True
            )
        )
        self.base_abbrevs = list(self.base_stats.values_list("abbreviation", flat=True))
        self.sum_abbrevs = list(
            self.sum_composites.values_list("abbreviation", flat=True)
        )
        self.pct_abbrevs = list(
            self.pct_composites.values_list("abbreviation", flat=True)
        )
        self.all_calc_abbrevs = self.sum_abbrevs + self.pct_abbrevs

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
            .values("player_id", "period", "stat_type__abbreviation")
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
                rec["stat_type__abbreviation"],
                rec["count"],
            )
            if pid in summary and per <= self.game.current_period:
                summary[pid]["periods"][per]["base_stats"][abbr] = cnt

    def _compute_sum_composites(self, summary):
        for comp in self.sum_composites:
            comps = [c.abbreviation for c in comp.composite_stats.all()]
            for data in summary.values():
                for pd in data["periods"].values():
                    total = sum(
                        pd["base_stats"].get(c, 0) + pd["calculated_stats"].get(c, 0)
                        for c in comps
                    )
                    pd["calculated_stats"][comp.abbreviation] = total

    def _compute_pct_composites(self, summary):
        for comp in self.pct_composites:
            comps = [c.abbreviation for c in comp.composite_stats.all()]
            if len(comps) != 2:
                continue
            made_abbr = next((c for c in comps if c.endswith("MA")), None)
            att_abbr = next((c for c in comps if c.endswith(("AT", "MS"))), None)
            if not made_abbr or not att_abbr:
                continue

            for data in summary.values():
                for pd in data["periods"].values():
                    made = pd["base_stats"].get(made_abbr, 0) + pd[
                        "calculated_stats"
                    ].get(made_abbr, 0)
                    att = pd["base_stats"].get(att_abbr, 0) + pd[
                        "calculated_stats"
                    ].get(att_abbr, 0)
                    pct = round((made / att) * 100, 1) if att else 0.0
                    pd["calculated_stats"][comp.abbreviation] = pct

    def _build_response(self, summary):
        response = []
        for data in summary.values():
            total_base = defaultdict(int)
            total_calc = defaultdict(float)
            pct_components = defaultdict(lambda: {"made": 0, "att": 0})
            periods_out = []

            for per in range(1, self.game.current_period + 1):
                pd = data["periods"][per]

                # Points
                pts = sum(
                    (
                        pd["base_stats"].get(s.abbreviation, 0)
                        + pd["calculated_stats"].get(s.abbreviation, 0)
                    )
                    * s.point_value
                    for s in self.all_stats
                    if s.point_value
                )

                # Filter stats
                fb = {
                    k: v
                    for k, v in pd["base_stats"].items()
                    if k not in self.counter_abbrevs
                }
                fc = {
                    k: int(v) if not k.endswith("_PC") else v
                    for k, v in pd["calculated_stats"].items()
                    if k not in self.counter_abbrevs
                }

                # Totals
                for k, v in fb.items():
                    total_base[k] += v
                for k, v in fc.items():
                    total_calc[k] += v

                # Track components for _PC recalculation
                for comp in self.pct_composites:
                    comps = [c.abbreviation for c in comp.composite_stats.all()]
                    if len(comps) != 2:
                        continue
                    made_abbr = next((c for c in comps if c.endswith("MA")), None)
                    att_abbr = next(
                        (c for c in comps if c.endswith("AT") or c.endswith("MS")), None
                    )
                    if not made_abbr or not att_abbr:
                        continue

                    made = pd["base_stats"].get(made_abbr, 0) + pd[
                        "calculated_stats"
                    ].get(made_abbr, 0)
                    att = pd["base_stats"].get(att_abbr, 0) + pd[
                        "calculated_stats"
                    ].get(att_abbr, 0)

                    pct_components[comp.abbreviation]["made"] += made
                    pct_components[comp.abbreviation]["att"] += att

                periods_out.append(
                    {
                        "period": per,
                        "base_stats": fb,
                        "calculated_stats": fc,
                        "points": pts,
                    }
                )

            # Recalculate percentage stats properly
            for abbr, val in pct_components.items():
                made = val["made"]
                att = val["att"]
                total_calc[abbr] = round((made / att) * 100, 1) if att else 0.0

            # Force all non _PC calculated totals to be int
            for k in list(total_calc.keys()):
                if not k.endswith("_PC"):
                    total_calc[k] = int(total_calc[k])

            response.append(
                {
                    "id": data["player_id"],
                    "name": data["player_name"],
                    "jersey_number": data["jersey_number"],
                    "team_id": data["team_id"],
                    "periods": periods_out,
                    "total_points": sum(p["points"] for p in periods_out),
                    "total_stats": {
                        "base_stats": dict(total_base),
                        "calculated_stats": dict(total_calc),
                    },
                }
            )

        return response

    def get_summary(self):
        summary = self._build_initial_summary()
        self._populate_base(summary)
        self._compute_sum_composites(summary)
        self._compute_pct_composites(summary)
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

        # handle the “counter” or “related” stat if configured
        rel = self.stat_type.related_stat
        if rel and self.stat_type.is_counter:
            PlayerStat.objects.update_or_create(
                player=self.player,
                game=self.game,
                stat_type=rel,
                period=self.game.current_period,
                defaults={},  # no extra fields to update
            )

        # bump the game’s score aggregates
        self.game.update_scores()

        return stat

class TeamStatsSummaryService:
    def __init__(self, game_id):
        self.game = Game.objects.select_related("home_team", "away_team").get(pk=game_id)
        self.teams = [self.game.home_team, self.game.away_team]
        self.all_stats = SportStatType.objects.filter(sport=self.game.sport)
        self.base_stats = self.all_stats.filter(composite_stats__isnull=True)
        self.sum_composites = self.all_stats.filter(
            composite_stats__isnull=False, calculation_type="sum"
        ).prefetch_related("composite_stats")
        self.pct_composites = self.all_stats.filter(
            composite_stats__isnull=False, calculation_type="percentage"
        ).prefetch_related("composite_stats")

        # Counter stats configuration
        self.counter_abbrevs = set(
            self.all_stats.filter(is_counter=True).values_list("abbreviation", flat=True)
        )
        self.base_abbrevs = list(self.base_stats.values_list("abbreviation", flat=True))
        self.sum_abbrevs = list(self.sum_composites.values_list("abbreviation", flat=True))
        self.pct_abbrevs = list(self.pct_composites.values_list("abbreviation", flat=True))
        self.all_calc_abbrevs = self.sum_abbrevs + self.pct_abbrevs

    def _aggregate_base_stats(self):
        return (
            PlayerStat.objects.filter(game=self.game, stat_type__in=self.base_stats)
            .values("player__team", "period", "stat_type__abbreviation")
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
                        "calculated_stats": dict.fromkeys(self.all_calc_abbrevs, 0.0),
                    }
                    for period in range(1, self.game.current_period + 1)
                },
                "total_base_stats": dict.fromkeys(self.base_abbrevs, 0),
                "total_calculated_stats": dict.fromkeys(self.all_calc_abbrevs, 0.0),
            }
        return summary

    def _populate_base(self, summary):
        """Populate base stats from database records"""
        for rec in self._aggregate_base_stats():
            team_id = rec["player__team"]
            period = rec["period"]
            abbr = rec["stat_type__abbreviation"]
            count = rec["total"]

            if team_id in summary and period <= self.game.current_period:
                summary[team_id]["periods"][period]["base_stats"][abbr] += count

    def _compute_sum_composites(self, summary):
        """Calculate sum-based composite stats"""
        for comp in self.sum_composites:
            components = [c.abbreviation for c in comp.composite_stats.all()]
            for team_data in summary.values():
                for period_data in team_data["periods"].values():
                    total = sum(
                        period_data["base_stats"].get(c, 0) +
                        period_data["calculated_stats"].get(c, 0)
                        for c in components
                    )
                    period_data["calculated_stats"][comp.abbreviation] = total

    def _compute_pct_composites(self, summary):
        """Calculate percentage-based composite stats"""
        for comp in self.pct_composites:
            components = [c.abbreviation for c in comp.composite_stats.all()]
            if len(components) != 2:
                continue
                
            made_abbr = next((c for c in components if c.endswith("MA")), None)
            att_abbr = next((c for c in components if c.endswith(("AT", "MS"))), None)
            
            if not made_abbr or not att_abbr:
                continue

            for team_data in summary.values():
                for period_data in team_data["periods"].values():
                    made = (
                        period_data["base_stats"].get(made_abbr, 0) +
                        period_data["calculated_stats"].get(made_abbr, 0)
                    )
                    att = (
                        period_data["base_stats"].get(att_abbr, 0) +
                        period_data["calculated_stats"].get(att_abbr, 0)
                    )
                    period_data["calculated_stats"][comp.abbreviation] = (
                        round((made / att) * 100, 1) if att else 0.0
                    )

    def _build_response(self, summary):
        """Build final response with counters excluded"""
        response = {}
        for team_id, team_data in summary.items():
            periods_out = []
            total_points = 0
            pct_components = defaultdict(lambda: {"made": 0, "att": 0})

            for period in range(1, self.game.current_period + 1):
                period_data = team_data["periods"][period]

                # Calculate points (includes counters if they have point_value)
                points = sum(
                    (period_data["base_stats"].get(s.abbreviation, 0) +
                     period_data["calculated_stats"].get(s.abbreviation, 0)
                    ) * s.point_value
                    for s in self.all_stats
                    if s.point_value
                )
                total_points += points

                # Filter out counter stats from response
                filtered_base = {
                    k: v 
                    for k, v in period_data["base_stats"].items()
                    if k not in self.counter_abbrevs
                }
                filtered_calc = {
                    k: int(v) if not k.endswith("_PC") else v
                    for k, v in period_data["calculated_stats"].items()
                    if k not in self.counter_abbrevs
                }

                # Track components for total percentages
                for comp in self.pct_composites:
                    components = [c.abbreviation for c in comp.composite_stats.all()]
                    if len(components) != 2:
                        continue
                        
                    made_abbr = next((c for c in components if c.endswith("MA")), None)
                    att_abbr = next((c for c in components if c.endswith(("AT", "MS"))), None)
                    
                    if made_abbr and att_abbr:
                        pct_components[comp.abbreviation]["made"] += (
                            period_data["base_stats"].get(made_abbr, 0) +
                            period_data["calculated_stats"].get(made_abbr, 0)
                        )
                        pct_components[comp.abbreviation]["att"] += (
                            period_data["base_stats"].get(att_abbr, 0) +
                            period_data["calculated_stats"].get(att_abbr, 0)
                        )

                periods_out.append({
                    "period": period,
                    "base_stats": filtered_base,
                    "calculated_stats": filtered_calc,
                    "points": points,
                })

            # Calculate total stats
            total_base = {k: team_data["total_base_stats"][k] for k in self.base_abbrevs}
            total_calc = team_data["total_calculated_stats"].copy()

            # Recalculate total percentages
            for comp in self.pct_composites:
                abbr = comp.abbreviation
                made = pct_components[abbr]["made"]
                att = pct_components[abbr]["att"]
                total_calc[abbr] = round((made / att) * 100, 1) if att else 0.0

            # Filter counters from totals
            filtered_total_base = {
                k: v 
                for k, v in total_base.items() 
                if k not in self.counter_abbrevs
            }
            filtered_total_calc = {
                k: int(v) if not k.endswith("_PC") else v
                for k, v in total_calc.items()
                if k not in self.counter_abbrevs
            }

            response[team_id] = {
                "team_id": team_data["team_id"],
                "team_name": team_data["team_name"],
                "periods": periods_out,
                "total_points": total_points,
                "total_stats": {
                    "base_stats": filtered_total_base,
                    "calculated_stats": filtered_total_calc,
                },
            }

        return {
            "home_team": response[self.game.home_team.id],
            "away_team": response[self.game.away_team.id],
        }

    def get_summary(self):
        """Main entry point"""
        summary = self._build_initial_summary()
        self._populate_base(summary)
        self._compute_sum_composites(summary)
        self._compute_pct_composites(summary)
        return self._build_response(summary)