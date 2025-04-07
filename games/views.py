from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from rest_framework.exceptions import ValidationError
from django.db.models import Value, IntegerField
from .models import Game, PlayerStat, Substitution
from teams.models import Player
from sports.models import SportStatType
from .serializers import (
    GameSerializer,
    GameActionSerializer,
    PlayerStatRecordSerializer,
    RecordableStatSerializer,
    PlayerStatSerializer,
    GamePlayerSerializer,
    StartingLineupSerializer,
    SubstitutionSerializer,
    GameCurrentPlayersSerializer,
)
from sports_management.permissions import IsAdminOrCoachUser
from collections import defaultdict
from django.db.models import Count


class PlayerStatViewSet(viewsets.ModelViewSet):
    queryset = PlayerStat.objects.select_related("player__team", "game", "stat_type")
    serializer_class = PlayerStatSerializer

    @action(detail=False, methods=["get"])
    def recordable_stats(self, request):
        game_id = request.query_params.get("game_id")
        if not game_id:
            return Response({"error": "game_id parameter required"}, status=400)

        try:
            game = Game.objects.get(pk=game_id)
            stats = SportStatType.objects.filter(
                sport=game.sport, composite_stats__isnull=True
            ).annotate(
                current_period=Value(game.current_period, output_field=IntegerField())
            )
            serializer = RecordableStatSerializer(stats, many=True)
            return Response(serializer.data)
        except Game.DoesNotExist:
            return Response({"error": "Game not found"}, status=404)

    @action(detail=False, methods=["post"])
    def record(self, request):
        serializer = PlayerStatRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        game = serializer.validated_data["game"]

        if game.status != Game.Status.IN_PROGRESS:
            return Response(
                {"error": "Game is not in progress"}, status=status.HTTP_400_BAD_REQUEST
            )

        stat = PlayerStat.objects.create(
            player=serializer.validated_data["player"],
            game=game,
            stat_type=serializer.validated_data["stat_type"],
            period=game.current_period,
        )

        self._handle_related_stats(stat)
        game.update_scores()
        return Response(PlayerStatSerializer(stat).data, status=status.HTTP_201_CREATED)

    def _handle_related_stats(self, stat):
        if stat.stat_type.related_stat and stat.stat_type.is_counter:
            PlayerStat.objects.update_or_create(
                player=stat.player,
                game=stat.game,
                stat_type=stat.stat_type.related_stat,
                period=stat.period,
            )

    @action(detail=False, methods=["get"])
    def stats_summary(self, request):
        game_id = request.query_params.get("game_id")
        team = request.query_params.get("team")

        if not game_id:
            return Response({"error": "game_id parameter required"}, status=400)

        try:
            game = Game.objects.select_related("home_team", "away_team").get(pk=game_id)
        except Game.DoesNotExist:
            return Response({"error": "Game not found"}, status=404)

        # determine which teams to include
        teams = []
        if team == "home_team":
            teams = [game.home_team]
        elif team == "away_team":
            teams = [game.away_team]
        else:
            teams = [game.home_team, game.away_team]

        # fetch stat types
        all_stats = SportStatType.objects.filter(sport=game.sport)
        base_stats = all_stats.filter(composite_stats__isnull=True)
        sum_composites = all_stats.filter(
            composite_stats__isnull=False, calculation_type="sum"
        )
        pct_composites = all_stats.filter(
            composite_stats__isnull=False, calculation_type="percentage"
        )

        # abbreviations
        counter_abbrevs = set(
            all_stats.filter(is_counter=True, calculation_type="none").values_list(
                "abbreviation", flat=True
            )
        )
        base_abbrevs = list(base_stats.values_list("abbreviation", flat=True))
        sum_abbrevs = list(sum_composites.values_list("abbreviation", flat=True))
        pct_abbrevs = list(pct_composites.values_list("abbreviation", flat=True))
        all_calc_abbrevs = sum_abbrevs + pct_abbrevs

        # aggregate base stats per player per period
        base_agg = (
            PlayerStat.objects.filter(
                game=game, stat_type__in=base_stats, player__team__in=teams
            )
            .values("player_id", "period", "stat_type__abbreviation")
            .annotate(count=Count("id"))
        )

        # aggregate sum composites per player per period by summing their components
        # we prefetch the M2M composite_stats relationship
        sum_comp_map = {
            comp.abbreviation: list(
                comp.composite_stats.values_list("abbreviation", flat=True)
            )
            for comp in sum_composites.prefetch_related("composite_stats")
        }

        # build an in-Python structure for fast lookup
        summary = {}
        for player in Player.objects.filter(team__in=teams).select_related("user"):
            summary[player.pk] = {
                "player_id": player.user.id,
                "player_name": player.user.get_full_name(),
                "jersey_number": player.jersey_number,
                "team_id": player.team.id,
                "periods": {
                    p: {
                        "base_stats": dict.fromkeys(base_abbrevs, 0),
                        "calculated_stats": dict.fromkeys(all_calc_abbrevs, 0),
                    }
                    for p in range(1, game.current_period + 1)
                },
            }

        # populate base stats
        for rec in base_agg:
            pid, per, abbr, cnt = (
                rec["player_id"],
                rec["period"],
                rec["stat_type__abbreviation"],
                rec["count"],
            )
            if pid in summary and per <= game.current_period:
                summary[pid]["periods"][per]["base_stats"][abbr] = cnt

        # compute sum composites
        for cs_abbr, components in sum_comp_map.items():
            for pid, data in summary.items():
                for per, pd in data["periods"].items():
                    total = sum(
                        pd["base_stats"].get(c, 0) + pd["calculated_stats"].get(c, 0)
                        for c in components
                    )
                    pd["calculated_stats"][cs_abbr] = total

        # compute percentage composites
        for comp in pct_composites.prefetch_related('composite_stats'):
            comps = list(comp.composite_stats.values_list('abbreviation', flat=True))
            if len(comps) != 2:
                continue
            made_abbr = next((c for c in comps if c.endswith('MA')), None)
            att_abbr  = next((c for c in comps if c.endswith(('AT','MS'))), None)
            if not made_abbr or not att_abbr:
                continue

            for pid, data in summary.items():
                for per, pd in data['periods'].items():
                    made = pd['base_stats'].get(made_abbr, 0) \
                         + pd['calculated_stats'].get(made_abbr, 0)
                    att  = pd['base_stats'].get(att_abbr, 0) \
                         + pd['calculated_stats'].get(att_abbr, 0)
                    pct  = round((made/att)*100,1) if att else 0.0
                    pd['calculated_stats'][comp.abbreviation] = pct

        # build final response
        response = []
        for data in summary.values():
            total_base = defaultdict(int)
            total_calc = defaultdict(float)
            periods_out = []

            for per in range(1, game.current_period + 1):
                pd = data["periods"][per]
                # compute points
                pts = sum(
                    (
                        pd["base_stats"].get(s.abbreviation, 0)
                        + pd["calculated_stats"].get(s.abbreviation, 0)
                    )
                    * s.point_value
                    for s in all_stats
                    if s.point_value
                )

                # filter out counter stats
                fb = {
                    k: v
                    for k, v in pd["base_stats"].items()
                    if k not in counter_abbrevs
                }
                fc = {
                    k: int(v) if k.endswith("_AT") else v
                    for k, v in pd["calculated_stats"].items()
                    if k not in counter_abbrevs
                }

                for k, v in fb.items():
                    total_base[k] += v
                for k, v in fc.items():
                    total_calc[k] += v

                periods_out.append(
                    {
                        "period": per,
                        "base_stats": fb,
                        "calculated_stats": fc,
                        "points": pts,
                    }
                )

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

        return Response(response)


class GameViewSet(viewsets.ModelViewSet):
    queryset = Game.objects.select_related(
        "sport", "home_team", "away_team"
    ).prefetch_related(
        "starting_lineup__player__user",
        "starting_lineup__position",
        "substitutions__substitute_in__user",
        "substitutions__substitute_out__user",
    )
    serializer_class = GameSerializer
    permission_classes = [IsAdminOrCoachUser]

    @action(detail=True, methods=["post"])
    def manage(self, request, pk=None):
        game = self.get_object()
        serializer = GameActionSerializer(data=request.data, context={"game": game})
        serializer.is_valid(raise_exception=True)

        try:
            action = serializer.validated_data["action"]
            if action == "start":
                game.start_game()
            elif action == "complete":
                game.complete_game()

            return Response(GameSerializer(game).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def update_scores(self, request, pk=None):
        game = self.get_object()
        game.update_scores()
        return Response(GameSerializer(game).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def players(self, request, pk=None):
        game = self.get_object()
        players = (
            Player.objects.select_related("user", "team")
            .prefetch_related("position")
            .filter(team__in=[game.home_team, game.away_team])
            .distinct()
        )
        serializer = GamePlayerSerializer(
            players, many=True, context={"request": request, "game": game}
        )

        teams = {
            "home_team": [p for p in serializer.data if p["team_side"] == "home_team"],
            "away_team": [p for p in serializer.data if p["team_side"] == "away_team"],
        }

        return Response(teams)

    @action(detail=True, methods=["get"])
    def current_players(self, request, pk=None):
        game = self.get_object()
        serializer = GameCurrentPlayersSerializer(game, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["get", "post", "delete"])
    def starting_lineup(self, request, pk=None):
        """Manage starting lineup for the game"""
        game = self.get_object()

        if request.method == "GET":
            return self._get_starting_lineup(game)
        elif request.method == "POST":
            return self._create_starting_lineup(game, request.data)

        elif request.method == "DELETE":
            return self._delete_starting_lineup(game)

    def _get_starting_lineup(self, game):
        lineup = game.starting_lineup.select_related("player", "position", "team")
        serializer = StartingLineupSerializer(lineup, many=True)

        # Split players into home/away teams
        home_players = []
        away_players = []

        for player_data in serializer.data:
            if player_data["team_side"] == "home":
                home_players.append(player_data)
            else:
                away_players.append(player_data)

        return Response(
            {"home_starting_lineup": home_players, "away_starting_lineup": away_players}
        )

    def _create_starting_lineup(self, game, data):
        if game.status != Game.Status.SCHEDULED:
            return Response(
                {"error": "Lineups can only be set for scheduled games"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate request structure
        if (
            not isinstance(data, dict)
            or "home_team" not in data
            or "away_team" not in data
        ):
            return Response(
                {"error": "Payload must contain home_team and away_team arrays"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        home_data = data["home_team"]
        away_data = data["away_team"]

        # Validate team assignments
        try:
            self._validate_team_players(game.home_team, home_data, "home_team")
            self._validate_team_players(game.away_team, away_data, "away_team")
        except ValidationError as e:
            return Response({"error": e.detail}, status=status.HTTP_400_BAD_REQUEST)

        # Combine into flat list for serializer
        combined_data = home_data + away_data

        with transaction.atomic():
            game.starting_lineup.all().delete()
            serializer = StartingLineupSerializer(
                data=combined_data,
                many=True,
                context={"game": game, "request": self.request},
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

            try:
                self._validate_lineup_completeness(game)
            except ValidationError as e:
                return Response({"error": e.detail}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "home_team": [p for p in serializer.data if p["team_side"] == "home"],
                "away_team": [p for p in serializer.data if p["team_side"] == "away"],
            },
            status=status.HTTP_201_CREATED,
        )

    def _validate_team_players(self, expected_team, players, team_side):
        """Validate all players in a team section belong to that team"""
        if not isinstance(players, list):
            raise ValidationError({team_side: "Must be an array of players"})

        player_user_ids = [p.get("player") for p in players]  # These are user IDs

        # Check for missing player IDs
        if None in player_user_ids:
            raise ValidationError({team_side: "All entries must have a player ID"})

        # Get actual players using user_id
        players = Player.objects.filter(
            user_id__in=player_user_ids
        )  # Changed to user_id__in

        if players.count() != len(player_user_ids):
            raise ValidationError({team_side: "Invalid player IDs provided"})

        # Verify team membership
        for player in players:
            if player.team != expected_team:
                raise ValidationError(
                    {team_side: f"Player {player.user_id} belongs to wrong team"}
                )

    def _validate_lineup_completeness(self, game):
        sport = game.sport
        home_count = game.starting_lineup.filter(team=game.home_team).count()
        away_count = game.starting_lineup.filter(team=game.away_team).count()

        errors = {}
        if home_count != sport.max_players_on_field:
            errors["home_team"] = f"Needs exactly {sport.max_players_on_field} starters"
        if away_count != sport.max_players_on_field:
            errors["away_team"] = f"Needs exactly {sport.max_players_on_field} starters"

        if errors:
            raise ValidationError(errors)

    def _delete_starting_lineup(self, game):
        if game.status != Game.Status.SCHEDULED:
            return Response(
                {"error": "Can only clear lineup for scheduled games"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        count, _ = game.starting_lineup.all().delete()
        return Response({"deleted": count}, status=status.HTTP_204_NO_CONTENT)


class SubstitutionViewSet(viewsets.ModelViewSet):
    queryset = Substitution.objects.select_related(
        "game", "substitute_in", "substitute_out"
    )
    serializer_class = SubstitutionSerializer
    permission_classes = [IsAdminOrCoachUser]

    def get_queryset(self):
        game_id = self.request.query_params.get("game_id")
        if game_id:
            return self.queryset.filter(game_id=game_id)
        return self.queryset

    @action(detail=True, methods=["post"])
    def undo(self, request, pk=None):
        substitution = self.get_object()
        substitution.delete()
        return Response({"status": "Substitution undone"}, status=status.HTTP_200_OK)
