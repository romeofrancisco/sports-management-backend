from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from rest_framework.exceptions import ValidationError
from django.shortcuts import get_object_or_404
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
        if not game_id:
            return Response({"error": "game_id parameter required"}, status=400)

        try:
            game = Game.objects.get(pk=game_id)
            current_period = game.current_period
            sport = game.sport

            # Get all relevant stats
            all_stats = SportStatType.objects.filter(sport=sport)
            base_stats = all_stats.filter(composite_stats__isnull=True)
            composite_stats = all_stats.filter(composite_stats__isnull=False).exclude(
                abbreviation__endswith=("_AT", "_PC")
            )

            # Get players and base stats data
            players = Player.objects.filter(team__in=[game.home_team, game.away_team])
            stat_records = PlayerStat.objects.filter(
                game=game, stat_type__in=base_stats
            ).select_related("player", "stat_type")

        except Game.DoesNotExist:
            return Response({"error": "Game not found"}, status=404)

        # Initialize data structure
        summary = {}
        for player in players:
            summary[player.user.id] = {
                "player_id": player.user.id,
                "player_name": player.user.get_full_name(),
                "team_id": player.team.id,
                "periods": {
                    period: {
                        "base_stats": defaultdict(int),
                        "calculated_stats": defaultdict(float),
                    }
                    for period in range(1, current_period + 1)
                },
            }

        # Populate base stats
        for stat in stat_records:
            player_id = stat.player.user.id
            period = stat.period
            abbrev = stat.stat_type.abbreviation

            if player_id in summary and period <= current_period:
                summary[player_id]["periods"][period]["base_stats"][abbrev] += 1

        # Calculate automatic _AT and _PC stats
        for player_data in summary.values():
            for period_data in player_data["periods"].values():
                base_stats = period_data["base_stats"]
                calculated_stats = period_data["calculated_stats"]

                ma_abbrevs = [k for k in base_stats.keys() if k.endswith("_MA")]
                for ma_abbrev in ma_abbrevs:
                    prefix = ma_abbrev[:-3]
                    ms_abbrev = f"{prefix}_MS"
                    at_abbrev = f"{prefix}_AT"
                    pc_abbrev = f"{prefix}_PC"

                    ma = base_stats.get(ma_abbrev, 0)
                    ms = base_stats.get(ms_abbrev, 0)
                    calculated_stats[at_abbrev] = ma + ms

                    if calculated_stats[at_abbrev] > 0:
                        calculated_stats[pc_abbrev] = round(
                            (ma / calculated_stats[at_abbrev]) * 100, 1
                        )
                    else:
                        calculated_stats[pc_abbrev] = 0.0

        # Process composite stats in correct order
        composite_sums = composite_stats.filter(calculation_type="sum")
        composite_percentages = composite_stats.filter(calculation_type="percentage")

        # Calculate sum composites first
        for cs in composite_sums:
            components = cs.composite_stats.all()
            component_abbrevs = [c.abbreviation for c in components]
            cs_abbrev = cs.abbreviation

            for player_data in summary.values():
                for period, period_data in player_data["periods"].items():
                    total = sum(
                        period_data["base_stats"].get(abbrev, 0)
                        + period_data["calculated_stats"].get(abbrev, 0)
                        for abbrev in component_abbrevs
                    )
                    period_data["calculated_stats"][cs_abbrev] = total

        # Then calculate percentages
        for cs in composite_percentages:
            components = cs.composite_stats.all()
            component_abbrevs = [c.abbreviation for c in components]
            cs_abbrev = cs.abbreviation

            if len(component_abbrevs) != 2:
                continue

            for player_data in summary.values():
                for period, period_data in player_data["periods"].items():
                    numerator, denominator = component_abbrevs
                    num_val = period_data["base_stats"].get(numerator, 0) + period_data[
                        "calculated_stats"
                    ].get(numerator, 0)
                    den_val = period_data["base_stats"].get(
                        denominator, 0
                    ) + period_data["calculated_stats"].get(denominator, 0)

                    percentage = (num_val / den_val * 100) if den_val else 0.0
                    period_data["calculated_stats"][cs_abbrev] = round(percentage, 1)

        # Build response
        response_data = []
        for player_id, data in summary.items():
            periods_list = []
            for period_num in range(1, current_period + 1):
                period_data = data["periods"][period_num]
                periods_list.append(
                    {
                        "period": period_num,
                        "base_stats": dict(period_data["base_stats"]),
                        "calculated_stats": dict(period_data["calculated_stats"]),
                    }
                )

            response_data.append(
                {
                    "player_id": data["player_id"],
                    "player_name": data["player_name"],
                    "team_id": data["team_id"],
                    "periods": periods_list,
                }
            )

        return Response(response_data)


class GameViewSet(viewsets.ModelViewSet):
    queryset = Game.objects.select_related(
        "sport", "home_team", "away_team"
    ).prefetch_related(
        'starting_lineup__player__user',
        'starting_lineup__position',
        'substitutions__substitute_in__user',
        'substitutions__substitute_out__user'
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
        serializer = GameCurrentPlayersSerializer(game, context={'request': request})
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
