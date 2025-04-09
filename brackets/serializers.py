from rest_framework import serializers
from .models import Bracket, BracketRound, BracketMatch
from teams.models import Team
from games.serializers import GameSerializer

class BracketMatchSerializer(serializers.ModelSerializer):
    home_team = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all(), required=False)
    away_team = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all(), required=False)
    game = GameSerializer(required=False)

    class Meta:
        model = BracketMatch
        fields = ['id', 'bracket', 'round', 'home_team', 'away_team', 'game']

class BracketRoundSerializer(serializers.ModelSerializer):
    matches = BracketMatchSerializer(many=True, read_only=True)

    class Meta:
        model = BracketRound
        fields = ['id', 'bracket', 'round_number', 'created_at', 'matches']

class BracketSerializer(serializers.ModelSerializer):
    rounds = BracketRoundSerializer(many=True, read_only=True)

    class Meta:
        model = Bracket
        fields = ['id', 'season', 'elimination_type', 'created_at', 'updated_at', 'rounds']
