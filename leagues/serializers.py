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
    league_name = serializers.SerializerMethodField()
    league = LeagueSerializer(read_only=True)
    has_bracket = serializers.SerializerMethodField()
    games_count = serializers.IntegerField(read_only=True)
    games_played = serializers.IntegerField(read_only=True)
    avg_points_per_game = serializers.FloatField(read_only=True)
    
    class Meta:
        model = Season
        fields = ['id', 'name', 'league', 'year', 'status', 'start_date', 'end_date', 
                 'has_bracket', 'games_count', 'games_played', 'avg_points_per_game', 'teams', 'is_recorded', 'league_name', 'teams_list']
        read_only_fields = ['league', 'team_lists']
        extra_kwargs = {"teams":{"write_only": True}}

    def validate(self, data):
        start = data.get('start_date')
        end = data.get('end_date')
        if start and end and start >= end:
            raise serializers.ValidationError("End date must be after start date")
        return data
    
    def get_has_bracket(self, obj):
        return hasattr(obj, 'bracket')
    
    def get_league_name(self, obj):
        return obj.league.name
    
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

class LeagueStatisticsSerializer(serializers.Serializer):
    """Serializer for league statistics endpoint"""
    teams_count = serializers.IntegerField()
    seasons_count = serializers.IntegerField()
    active_seasons = serializers.IntegerField()
    games_count = serializers.IntegerField()
    current_season = SeasonSerializer(required=False, allow_null=True)

class TeamFormSerializer(serializers.Serializer):
    """Serializer for team form data"""
    result = serializers.CharField(max_length=1)  # W, L, D
    score = serializers.CharField(max_length=10)
    opponent = serializers.CharField()
    date = serializers.CharField()

class TeamPerformanceSerializer(serializers.Serializer):
    """Serializer for detailed team performance metrics"""
    team_id = serializers.IntegerField()
    team_name = serializers.CharField()
    team_logo = serializers.URLField(allow_null=True)
    games_played = serializers.IntegerField()
    avg_points_scored = serializers.FloatField()
    avg_points_conceded = serializers.FloatField()
    first_half_wins = serializers.IntegerField()
    second_half_wins = serializers.IntegerField()
    point_differential = serializers.FloatField()
    max_win_streak = serializers.IntegerField()
    current_streak = serializers.IntegerField()

class SeasonComparisonSerializer(serializers.Serializer):
    """Serializer for season comparison data"""
    id = serializers.IntegerField()
    name = serializers.CharField()
    year = serializers.IntegerField()
    champion = serializers.CharField(allow_null=True)
    teams_count = serializers.IntegerField()
    games_count = serializers.IntegerField()
    avg_points_per_game = serializers.FloatField()
    top_team = serializers.CharField(allow_null=True)