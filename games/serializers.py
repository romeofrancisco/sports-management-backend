# api/serializers.py
from rest_framework import serializers
from .models import Game, PlayerStat
from teams.serializers import TeamSerializer
from teams.models import Team


class PlayerStatSerializer(serializers.ModelSerializer):
    player_name = serializers.CharField(
        source="player.user.get_full_name", read_only=True
    )
    stat_type_name = serializers.CharField(source="stat_type.name", read_only=True)
    team = serializers.SerializerMethodField()

    class Meta:
        model = PlayerStat
        fields = [
            "id",
            "player",
            "player_name",
            "game",
            "stat_type",
            "stat_type_name",
            "period",
            "success",
            "timestamp",
            "team",
        ]
        read_only_fields = ["timestamp", "team"]
        extra_kwargs = {"player": {"write_only": True}, "game": {"write_only": True}}

    def get_team(self, obj):
        return obj.player.team.id

    def validate(self, data):
        # Check game status
        if data["game"].status != Game.Status.IN_PROGRESS:
            raise serializers.ValidationError(
                "Stats can only be recorded for in-progress games"
            )

        # Validate period
        if data["period"] > data["game"].current_period:
            raise serializers.ValidationError("Cannot record stats for future periods")

        # Validate player-team-game relationship
        game_teams = [data["game"].home_team, data["game"].away_team]
        if data["player"].team not in game_teams:
            raise serializers.ValidationError("Player is not part of this game")

        # Validate stat type belongs to game sport
        if data["stat_type"].sport != data["game"].sport:
            raise serializers.ValidationError("Stat type doesn't match game sport")

        return data


class GameSerializer(serializers.ModelSerializer):
    home_team = TeamSerializer(read_only=True)
    away_team = TeamSerializer(read_only=True)
    status = serializers.ChoiceField(choices=Game.Status.choices)
    winner = serializers.SerializerMethodField()

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
            "home_team",
            "away_team",
            "home_team_id",
            "away_team_id",
            "date",
            "location",
            "status",
            "started_at",
            "ended_at",
            "duration",
            "notes",
            "home_team_score",
            "away_team_score",
            "current_period",
            "winner",
            "created_at",
        ]
        read_only_fields = ["created_at", "updated_at", "winner"]

    def get_winner(self, obj):
        return obj.winner.id if obj.winner else None

    def validate(self, data):
        # Get home_team and away_team from different possible sources
        home_team = data.get('home_team') or getattr(self.instance, 'home_team', None)
        away_team = data.get('away_team') or getattr(self.instance, 'away_team', None)
        
        if not home_team or not away_team:
            raise serializers.ValidationError("Both home and away teams are required")
            
        if home_team == away_team:
            raise serializers.ValidationError("Home and away teams cannot be the same")
            
        # Additional validation - teams must belong to the same sport
        if hasattr(data, 'sport'):
            sport = data['sport']
            if home_team.sport != sport or away_team.sport != sport:
                raise serializers.ValidationError("Teams must belong to the game's sport")
        
        return data


class GameActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=["start", "complete", "postpone"], required=True
    )
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_action(self, value):
        """Additional validation for game state transitions"""
        game = self.context.get("game")
        if not game:
            raise serializers.ValidationError("Game instance is required in context")

        valid_transitions = {
            "scheduled": ["start"],
            "in_progress": ["complete", "postpone"],
            "postponed": ["start"],
            # Add other transitions as needed
        }

        if value not in valid_transitions.get(game.status, []):
            raise serializers.ValidationError(
                f"Cannot {value} a game in {game.status} state"
            )
        return value
