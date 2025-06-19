from rest_framework import serializers
from .models import Game, PlayerStat, StartingLineup, Substitution, GameCoachPermission
from teams.serializers import TeamSerializer
from teams.models import Team, Player
from sports.models import SportStatType, Position, Sport
from sports.serializers import PositionSerializer
from django.core.exceptions import ValidationError
from leagues.models import League, Season


class GameCoachPermissionSerializer(serializers.ModelSerializer):
    coach_name = serializers.CharField(source='coach.get_full_name', read_only=True)
    coach_email = serializers.CharField(source='coach.email', read_only=True)
    assigned_by_name = serializers.CharField(source='assigned_by.get_full_name', read_only=True)
    
    class Meta:
        model = GameCoachPermission
        fields = [
            'id', 'game', 'coach', 'coach_name', 'coach_email', 
            'assigned_by', 'assigned_by_name', 'assigned_at'
        ]
        read_only_fields = ['assigned_by', 'assigned_at']


class PositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Position
        fields = ["id", "name", "abbreviation"]


class PlayerStatRecordSerializer(serializers.ModelSerializer):
    game = serializers.PrimaryKeyRelatedField(queryset=Game.objects.all())
    player = serializers.PrimaryKeyRelatedField(queryset=Player.objects.all())
    stat_type = serializers.PrimaryKeyRelatedField(queryset=SportStatType.objects.all())

    class Meta:
        model = PlayerStat
        fields = ["game", "player", "stat_type"]


class PlayerStatSerializer(serializers.ModelSerializer):
    player_name = serializers.CharField(
        source="player.user.get_full_name", read_only=True
    )
    team = serializers.SerializerMethodField()
    stat_details = serializers.SerializerMethodField()

    class Meta:
        model = PlayerStat
        fields = [
            "id",
            "player",
            "player_name",
            "game",
            "stat_type",
            "stat_details",
            "period",
            "timestamp",
            "team",
        ]

    def get_team(self, obj):
        return obj.player.team.id

    def get_stat_details(self, obj):
        return {
            "name": obj.stat_type.name,
            "code": obj.stat_type.code,
            "point_value": obj.stat_type.point_value,
        }


class RecordableStatSerializer(serializers.ModelSerializer):
    current_period = serializers.IntegerField()
    button_type = serializers.SerializerMethodField()

    class Meta:
        model = SportStatType
        fields = [
            "id",
            "name",
            "display_name",
            "code",
            "point_value",
            "current_period",
            "button_type",
        ]

    def get_button_type(self, obj):
        if obj.is_negative:
            return "negative"
        elif obj.is_points and obj.point_value > 0:
            return "made"
        elif obj.is_points and obj.point_value < 1:
            return "miss"
        return "info"


class GameSerializer(serializers.ModelSerializer):
    home_team = TeamSerializer(read_only=True)
    away_team = TeamSerializer(read_only=True)
    status = serializers.ChoiceField(choices=Game.Status.choices)
    winner = serializers.SerializerMethodField()
    lineup_status = serializers.SerializerMethodField()
    score_summary = serializers.SerializerMethodField()
    sport_slug = serializers.CharField(source="sport.slug", read_only=True)
    sport = serializers.PrimaryKeyRelatedField(queryset=Sport.objects.all(), read_only=False)    # Nested league and season data for frontend display
    league = serializers.SerializerMethodField()
    season = serializers.SerializerMethodField()
    assigned_coaches = serializers.SerializerMethodField()

    # For write operations
    home_team_id = serializers.PrimaryKeyRelatedField(
        queryset=Team.objects.all(), write_only=True, source="home_team"
    )
    away_team_id = serializers.PrimaryKeyRelatedField(
        queryset=Team.objects.all(), write_only=True, source="away_team"
    )
    league_id = serializers.PrimaryKeyRelatedField(
        queryset=League.objects.all(), write_only=True, source="league", required=False
    )
    season_id = serializers.PrimaryKeyRelatedField(
        queryset=Season.objects.all(), write_only=True, source="season", required=False
    )

    class Meta:
        model = Game
        fields = [
            "id",
            "sport",
            "sport_slug",
            "league",
            "season",
            "is_recorded",
            "score_summary",
            "type",
            "home_team",
            "away_team",
            "home_team_id",
            "away_team_id",
            "league_id",
            "season_id",
            "lineup_status",
            "date",
            "location",
            "status",
            "started_at",
            "ended_at",
            "duration",            "home_team_score",
            "away_team_score",            "current_period",
            "winner",
            "assigned_coaches",
            "created_at",
        ]
        read_only_fields = [
            "created_at",
            "updated_at",
            "winner",
        ]

    def create(self, validated_data):
        return super().create(validated_data)

    def get_winner(self, obj):
        return obj.winner.id if obj.winner else None
    
    def get_league(self, obj):
        """Return league data with name only for frontend display"""
        if obj.league:            return {
                "id": obj.league.id,
                "name": obj.league.name
            }
        return None
    
    def get_season(self, obj):
        """Return season data with name and year only for frontend display"""
        if obj.season:
            return {
                "id": obj.season.id,
                "name": obj.season.name,
                "year": obj.season.year
            }
        return None
    
    def get_assigned_coaches(self, obj):
        """Return list of coaches assigned to manage this game"""
        if obj.type == Game.Type.LEAGUE:
            permissions = obj.coach_permissions.select_related('coach').all()
            return [
                {
                    'id': perm.coach.id,
                    'name': perm.coach.get_full_name(),
                    'email': perm.coach.email,
                    'assigned_at': perm.assigned_at
                }
                for perm in permissions
            ]
        return []
    
    def get_score_summary(self, obj):
        return obj.score_summary

    def get_lineup_status(self, obj):
        return obj.get_lineup_status()

    def validate(self, data):
        home_team = data.get("home_team") or getattr(self.instance, "home_team", None)
        away_team = data.get("away_team") or getattr(self.instance, "away_team", None)

        if not home_team or not away_team:
            raise serializers.ValidationError("Both home and away teams are required")

        if home_team == away_team:
            raise serializers.ValidationError("Home and away teams cannot be the same")

        if "sport" in data:
            sport = data["sport"]
            if home_team.sport != sport or away_team.sport != sport:
                raise serializers.ValidationError("Teams must belong to the game's sport")

        return data


class GameActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=["start", "complete", "postpone", "next_period"], required=True
    )

    def validate_action(self, value):
        game = self.context["game"]
        valid_transitions = {
            Game.Status.SCHEDULED: ["start"],
            Game.Status.IN_PROGRESS: ["complete", "postpone", "next_period"],
            Game.Status.POSTPONED: ["start"],
            Game.Status.COMPLETED: [],
        }

        current_status = game.status
        allowed_actions = valid_transitions.get(current_status, [])

        if value not in allowed_actions:
            raise serializers.ValidationError(
                f"Cannot {value} a game in {current_status} state. "
                f"Allowed actions: {', '.join(allowed_actions)}"
            )

        return value


class GamePlayerSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="user.id", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    full_name = serializers.SerializerMethodField()
    short_name = serializers.SerializerMethodField()
    profile = serializers.ImageField(source="user.profile", read_only=True)
    team_side = serializers.SerializerMethodField()
    position = PositionSerializer(many=True)

    class Meta:
        model = Player
        fields = [
            "id",
            "first_name",
            "last_name",
            "full_name",
            "short_name",
            "profile",
            "jersey_number",
            "team",
            "team_side",
            "position",
        ]

    def get_full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"

    def get_short_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name[0]}."

    def get_team_side(self, obj):
        game = self.context["game"]
        return "home_team" if obj.team == game.home_team else "away_team"


class SubstitutionSerializer(serializers.ModelSerializer):
    substitute_in_name = serializers.CharField(
        source="substitute_in.user.get_full_name", read_only=True
    )
    substitute_out_name = serializers.CharField(
        source="substitute_out.user.get_full_name", read_only=True
    )

    class Meta:
        model = Substitution
        fields = [
            "id",
            "game",
            "substitute_in",
            "substitute_in_name",
            "substitute_out",
            "substitute_out_name",
            "period",
            "timestamp",
        ]
        extra_kwargs = {
            "game": {"write_only": True},
            "substitute_in": {"write_only": True},
            "substitute_out": {"write_only": True},
        }

    def validate(self, data):
        game = data["game"]
        sub_in = data["substitute_in"]
        sub_out = data["substitute_out"]

        # Can't substitute same player
        if sub_in == sub_out:
            raise serializers.ValidationError("Cannot substitute same player")

        # Validate period
        if data["period"] > game.current_period:
            raise serializers.ValidationError("Cannot substitute in future period")

        # Check if substitute_out is active
        if not sub_out.is_active_in_game(game):
            raise serializers.ValidationError("Substitute out player is not active")

        # Check if substitute_in is inactive
        if sub_in.is_active_in_game(game):
            raise serializers.ValidationError("Substitute in player is already active")

        return data


class CurrentPlayerSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="player.user.id")
    profile = serializers.ImageField(source="player.user.profile", read_only=True)
    first_name = serializers.CharField(source="player.user.first_name")
    last_name = serializers.CharField(source="player.user.last_name")
    jersey_number = serializers.IntegerField(source="player.jersey_number")
    position = PositionSerializer(source="player.position", many=True, read_only=True)
    team = serializers.IntegerField(source="player.team.id")
    short_name = serializers.SerializerMethodField()
    team_side = serializers.SerializerMethodField()

    class Meta:
        model = StartingLineup
        fields = [
            "id",
            "profile",
            "short_name",
            "first_name",
            "last_name",
            "position",
            "jersey_number",
            "team_side",
            "team",
        ]

    def get_short_name(self, obj):
        return f"{obj.player.user.first_name} {obj.player.user.last_name[0]}."

    def get_team_side(self, obj):
        game = obj.game
        return "home_team" if obj.team == game.home_team else "away_team"


class GameCurrentPlayersSerializer(serializers.ModelSerializer):
    home_players = serializers.SerializerMethodField()
    away_players = serializers.SerializerMethodField()
    current_period = serializers.IntegerField(read_only=True)

    class Meta:
        model = Game
        fields = ["id", "current_period", "home_players", "away_players"]

    def get_home_players(self, obj):
        players = obj.get_current_players(obj.home_team)
        return CurrentPlayerSerializer(players, many=True, context=self.context).data

    def get_away_players(self, obj):
        players = obj.get_current_players(obj.away_team)
        return CurrentPlayerSerializer(players, many=True, context=self.context).data


class StartingLineupSerializer(serializers.ModelSerializer):
    player_name = serializers.CharField(
        source="player.user.get_full_name", read_only=True
    )
    team_name = serializers.CharField(source="team.name", read_only=True)
    team_side = serializers.SerializerMethodField()
    position = PositionSerializer(source="player.position", many=True, read_only=True)

    class Meta:
        model = StartingLineup
        fields = [
            "player",
            "player_name",
            "position",
            "team",
            "team_name",
            "team_side",
        ]
        extra_kwargs = {
            "team": {"read_only": True},
            "game": {"write_only": True},
            "position": {"read_only": True},
        }

    def get_team_side(self, obj):
        """Determine if player is on home or away team"""
        return "home" if obj.team == obj.game.home_team else "away"

    def create(self, validated_data):
        # Get game from context
        game = self.context["game"]
        validated_data["game"] = game

        # Force is_starting to True
        validated_data["is_starting"] = True

        return super().create(validated_data)

    def validate(self, attrs):
        game = self.context["game"]
        player = attrs["player"]

        # Auto-assign team based on player's team
        attrs["team"] = player.team

        # Validate player belongs to game teams
        if player.team not in [game.home_team, game.away_team]:
            raise ValidationError("Player not in this game")

        return attrs


class GameSummarySerializer(serializers.ModelSerializer):
    """
    Simplified serializer for game analytics and summaries.
    Only includes essential data for charts and performance visualization.
    """
    home_team_name = serializers.CharField(source="home_team.name", read_only=True)
    away_team_name = serializers.CharField(source="away_team.name", read_only=True)
    winner_team_name = serializers.CharField(source="winner_team.name", read_only=True)
    sport_name = serializers.CharField(source="sport.name", read_only=True)
    
    class Meta:
        model = Game
        fields = [
            "id",
            "date", 
            "home_team_name",
            "away_team_name",
            "home_team_score",
            "away_team_score", 
            "status",
            "winner_team_name",
            "sport_name",
            "location"
        ]
        read_only_fields = fields
