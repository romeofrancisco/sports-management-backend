from rest_framework import serializers
from .models import League, Season
from sports.serializers import SportSerializer
from teams.models import Team

class LeagueSerializer(serializers.ModelSerializer):
    sport = SportSerializer()
    class Meta:
        model = League
        fields = ["id", "name", "logo", "sport"]
        read_only_fields = ['created_at']
        
class LeagueWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = League
        fields = ["id", "name", "logo", "sport"]
        read_only_fields = ['created_at']
        
class TeamSerializer(serializers.ModelSerializer):
    logo = serializers.SerializerMethodField()
    class Meta:
        model = Team
        fields = ["id", "name", "logo"]
        
        
    def get_logo(self, obj):
        request = self.context.get("request")
        if obj.logo and request:
            return request.build_absolute_uri(obj.logo.url)
        return None
    

class SeasonSerializer(serializers.ModelSerializer):
    teams_list = serializers.SerializerMethodField()
    has_bracket = serializers.SerializerMethodField()
    class Meta:
        model = Season
        fields = ['id', 'name', 'teams', "is_recorded", 'teams_list', 'league', 'year', 'status', 'has_bracket', 'start_date', 'end_date']
        read_only_fields = ['league', 'team_lists']
        extra_kwargs = {"teams":{"write_only": True}}

    def validate(self, data):
        start = data.get('start_date')
        end = data.get('end_date')
        if start and end and start.date() >= end:
            raise serializers.ValidationError("End date must be after start date")
        return data
    
    def get_has_bracket(self, obj):
        return hasattr(obj, 'bracket')
    
    def get_teams_list(self, obj):
        request = self.context.get("request")
        return TeamSerializer(obj.teams.all(), many=True, context={"request": request}).data
    
class TeamStandingsSerializer(serializers.ModelSerializer):
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