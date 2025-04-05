from rest_framework import serializers
from .models import Game, PlayerStat, StartingLineup, Substitution
from teams.serializers import TeamSerializer
from teams.models import Team, Player
from sports.models import SportStatType, Position
from sports.serializers import PositionSerializer
from django.core.exceptions import ValidationError


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
            "abbreviation": obj.stat_type.abbreviation,
            "point_value": obj.stat_type.point_value,
        }


class RecordableStatSerializer(serializers.ModelSerializer):
    current_period = serializers.IntegerField()
    button_type = serializers.SerializerMethodField()
    paired_stat_id = serializers.SerializerMethodField()  # Renamed for clarity
    paired_stat_abbrev = serializers.SerializerMethodField()

    class Meta:
        model = SportStatType
        fields = [
            "id",
            "name",
            "abbreviation",
            "point_value",
            "current_period",
            "button_type",
            "paired_stat_id",
            "paired_stat_abbrev",
        ]

    def get_button_type(self, obj):
        if obj.is_negative:
            return "negative"
        if obj.related_stat:
            return "miss"
        return "made" if obj.point_value > 0 else "info"

    def get_paired_stat_id(self, obj):
        if obj.related_stat:
            return obj.related_stat.id
        # For missed stats, find if any stat points to this one as related
        counterpart = SportStatType.objects.filter(related_stat=obj).first()
        return counterpart.id if counterpart else None

    def get_paired_stat_abbrev(self, obj):
        counterpart = (
            obj.related_stat
            if obj.related_stat
            else SportStatType.objects.filter(related_stat=obj).first()
        )
        return counterpart.abbreviation if counterpart else None


class GameSerializer(serializers.ModelSerializer):
    home_team = TeamSerializer(read_only=True)
    away_team = TeamSerializer(read_only=True)
    status = serializers.ChoiceField(choices=Game.Status.choices)
    winner = serializers.SerializerMethodField()
    lineup_status = serializers.SerializerMethodField()
    sport_slug = serializers.CharField(source="sport.slug", read_only=True)

    # For write operations
    home_team_id = serializers.PrimaryKeyRelatedField(
        queryset=Team.objects.all(), write_only=True, source="home_team"
    )
    away_team_id = serializers.PrimaryKeyRelatedField(
        queryset=Team.objects.all(), write_only=True, source="away_team"
    )
    

    class Meta:
        model = Game
        fields = [
            "id",
            "sport",
            "sport_slug",
            "league",
            "season",
            "home_team",
            "away_team",
            "home_team_id",
            "away_team_id",
            "lineup_status",
            "date",
            "location",
            "status",
            "started_at",
            "ended_at",
            "duration",
            "home_team_score",
            "away_team_score",
            "current_period",
            "winner",
            "created_at",
        ]
        read_only_fields = ["created_at", "updated_at", "winner", "home_team_score","away_team_score"]

    def get_winner(self, obj):
        return obj.winner.id if obj.winner else None
    
    def get_lineup_status(self, obj):
        return {
            'home_ready': obj.starting_lineup.filter(team=obj.home_team).count() >= obj.sport.max_players_on_field,
            'away_ready': obj.starting_lineup.filter(team=obj.away_team).count() >= obj.sport.max_players_on_field
        }

    def validate(self, data):
        # Get home_team and away_team from different possible sources
        home_team = data.get("home_team") or getattr(self.instance, "home_team", None)
        away_team = data.get("away_team") or getattr(self.instance, "away_team", None)

        if not home_team or not away_team:
            raise serializers.ValidationError("Both home and away teams are required")

        if home_team == away_team:
            raise serializers.ValidationError("Home and away teams cannot be the same")

        # Additional validation - teams must belong to the same sport
        if hasattr(data, "sport"):
            sport = data["sport"]
            if home_team.sport != sport or away_team.sport != sport:
                raise serializers.ValidationError(
                    "Teams must belong to the game's sport"
                )

        return data


class GameActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=["start", "complete", "postpone"], required=True
    )
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_action(self, value):
        game = self.context["game"]
        valid_transitions = {
            Game.Status.SCHEDULED: ["start"],
            Game.Status.IN_PROGRESS: ["complete", "postpone"],
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
    full_name = serializers.SerializerMethodField()
    short_name = serializers.SerializerMethodField()
    profile = serializers.ImageField(source="user.profile", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    team = serializers.SerializerMethodField()
    team_side = serializers.SerializerMethodField()
    position = PositionSerializer(many=True)

    class Meta:
        model = Player
        fields = [
            "id",
            "full_name",
            "short_name",
            "profile",
            "email",
            "jersey_number",
            "height",
            "weight",
            "team",
            "team_side",
            "position",
        ]

    def get_full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"
    
    def get_short_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name[0]}."

    def get_team(self, obj):
        return {
            "id": obj.team.id,
            "name": obj.team.name,
            "logo": obj.team.logo.url if obj.team.logo else None,
        }

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


class StartingLineupSerializer(serializers.ModelSerializer):
    player_name = serializers.CharField(source='player.user.get_full_name', read_only=True)
    team_name = serializers.CharField(source='team.name', read_only=True)
    position = serializers.PrimaryKeyRelatedField(queryset=Position.objects.all()) 
    team_side = serializers.SerializerMethodField()

    class Meta:
        model = StartingLineup
        fields = [
            'player', 'player_name', 
            'team', 'team_name', 'position',
            'team_side'
        ]
        extra_kwargs = {
            'team': {'read_only': True},  # Changed from write_only
            'game': {'write_only': True},
        }
        
    def get_team_side(self, obj):
        """Determine if player is on home or away team"""
        return 'home' if obj.team == obj.game.home_team else 'away'
    
    def create(self, validated_data):
        # Get game from context
        game = self.context['game']
        validated_data['game'] = game
        
        # Force is_starting to True
        validated_data['is_starting'] = True
        
        return super().create(validated_data)

    def validate(self, attrs):
        game = self.context['game']
        player = attrs['player']
        
        # Auto-assign team based on player's team
        attrs['team'] = player.team
        
        # Validate player belongs to game teams
        if player.team not in [game.home_team, game.away_team]:
            raise ValidationError("Player not in this game")
            
        return attrs

