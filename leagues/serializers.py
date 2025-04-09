from rest_framework import serializers
from .models import League, Season
from teams.serializers import TeamSerializer
from sports.serializers import SportSerializer
from teams.models import Team

class LeagueSerializer(serializers.ModelSerializer):
    teams = TeamSerializer(many=True)
    sport = SportSerializer(read_only=True)
    class Meta:
        model = League
        fields = ["id", "name", "sport", "teams"]
        read_only_fields = ['created_at']

class LeagueWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = League
        fields = ['name', 'sport', 'teams']

class SeasonSerializer(serializers.ModelSerializer):
    has_bracket = serializers.SerializerMethodField()
    class Meta:
        model = Season
        fields = ['id', 'league', 'year', 'status', 'has_bracket', 'start_date', 'end_date']
        read_only_fields = ['league']

    def validate(self, data):
        if data['start_date'] >= data['end_date']:
            raise serializers.ValidationError(
                "End date must be after start date"
            )
        return data
    
    def get_has_bracket(self, obj):
        return obj.brackets.exists()
    
class TeamStandingsSerializer(serializers.ModelSerializer):
    logo = serializers.SerializerMethodField()
    standings = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = ['id', 'name', 'logo', 'standings']

    def get_logo(self, obj):
        request = self.context.get('request')
        if obj.logo:
            return request.build_absolute_uri(obj.logo.url)
        return None

    def get_standings(self, obj):
        return self.context['standings_data'].get(obj.id, {})