# api/serializers.py
from rest_framework import serializers
from .models import Game, PlayerStat


class PlayerStatSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlayerStat
        fields = "__all__"

    def validate(self, data):
        # Ensure player is part of the game's teams
        if data["player"].team not in [data["game"].home_team, data["game"].away_team]:
            raise serializers.ValidationError("Player is not in this game.")
        return data


class GameSerializer(serializers.ModelSerializer):
    class Meta:
        model = Game
        fields = "__all__"
        read_only_fields = ["home_team_score", "away_team_score"]
