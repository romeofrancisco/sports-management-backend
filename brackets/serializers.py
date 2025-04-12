from rest_framework import serializers
from .models import Bracket, BracketRound, BracketMatch
from teams.models import Team
from games.models import Game

class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ['id', 'name', 'logo']

class BracketMatchSerializer(serializers.ModelSerializer):
    home_team = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all(), required=False, write_only=True)
    away_team = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all(), required=False, write_only=True)
    
        # For read operations
    home_team_details = TeamSerializer(source='home_team', read_only=True)
    away_team_details = TeamSerializer(source='away_team', read_only=True)

    game = serializers.PrimaryKeyRelatedField(queryset=Game.objects.all(), required=False,)
    
    next_match_id = serializers.IntegerField(
        source='next_match.id', 
        read_only=True,
        allow_null=True
    )

    class Meta:
        model = BracketMatch
        fields = [
            'id', 'bracket', 'round', 
            'home_team', 'away_team',  # For input
            'home_team_details', 'away_team_details',  # For output
            'game','winner', 'next_match_id'
        ]

class BracketRoundSerializer(serializers.ModelSerializer):
    matches = BracketMatchSerializer(many=True, read_only=True)

    class Meta:
        model = BracketRound
        fields = ['id', 'bracket', 'round_number', 'created_at', 'matches']

class BracketSerializer(serializers.ModelSerializer):
    rounds = BracketRoundSerializer(many=True, read_only=True)

    class Meta:
        model = Bracket
        fields = ['id', 'season', 'elimination_type', 'winner', 'is_complete', 'created_at', 'updated_at', 'rounds']
        read_only_fields = ["winner", "is_complete"]
