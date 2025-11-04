from rest_framework import serializers
from .models import Tournament
from sports.serializers import SportSerializer
from teams.models import Team


class TournamentSerializer(serializers.ModelSerializer):
    sport = SportSerializer()
    teams = serializers.SerializerMethodField()
    teams_count = serializers.SerializerMethodField()
    games_count = serializers.IntegerField(read_only=True)
    games_played = serializers.IntegerField(read_only=True)
    avg_points_per_game = serializers.FloatField(read_only=True)
    has_bracket = serializers.SerializerMethodField()
    bracket_type = serializers.CharField(source='bracket.elimination_type', read_only=True, allow_null=True)

    class Meta:
        model = Tournament
        fields = [
            "id",
            "name",
            "division",
            "logo",
            "sport",
            "teams",
            "teams_count",
            "games_count",
            "games_played",
            "avg_points_per_game",
            "status",
            "start_date",
            "end_date",
            "has_bracket",
            "bracket_type",
            "is_recorded",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_teams(self, obj):
        """Get basic team information"""
        from teams.serializers import SimpleTeamSerializer
        return SimpleTeamSerializer(obj.teams.all(), many=True, context=self.context).data

    def get_teams_count(self, obj):
        """Get total number of teams in the tournament"""
        return obj.teams.count()

    def get_has_bracket(self, obj):
        """Check if tournament has a bracket"""
        return hasattr(obj, 'bracket') and obj.bracket is not None


class TournamentWriteSerializer(serializers.ModelSerializer):
    teams = serializers.PrimaryKeyRelatedField(
        queryset=Team.objects.all(),
        many=True,
        required=False,
        allow_empty=True
    )
    
    class Meta:
        model = Tournament
        fields = [
            "id",
            "name",
            "division",
            "logo",
            "sport",
            "status",
            "start_date",
            "end_date",
            "is_recorded",
            "teams",
        ]
        read_only_fields = ["created_at", "updated_at"]
    
    def to_internal_value(self, data):
        # Handle teams when sent as JSON string in FormData
        if 'teams' in data and isinstance(data.get('teams'), str):
            import json
            try:
                data = data.copy() if hasattr(data, 'copy') else dict(data)
                data['teams'] = json.loads(data['teams'])
            except (json.JSONDecodeError, ValueError):
                pass
        
        return super().to_internal_value(data)
    
    def create(self, validated_data):
        teams = validated_data.pop('teams', [])
        tournament = Tournament.objects.create(**validated_data)
        if teams:
            tournament.teams.set(teams)
        return tournament
    
    def update(self, instance, validated_data):
        teams = validated_data.pop('teams', None)
        
        # Update basic fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update teams if provided
        if teams is not None:
            instance.teams.set(teams)
        
        return instance


class TeamSerializer(serializers.ModelSerializer):
    logo = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = ["id", "name", "logo", "slug"]

    def get_logo(self, obj):
        request = self.context.get("request")
        if obj.logo and request:
            return request.build_absolute_uri(obj.logo.url)
        return None


class TournamentTeamSerializer(serializers.ModelSerializer):
    """Serializer for teams with tournament-specific statistics"""
    teams = TeamSerializer(many=True, read_only=True)
    
    class Meta:
        model = Tournament
        fields = ["id", "name", "teams"]


class TeamStandingsSerializer(serializers.Serializer):
    """Serializer for tournament standings data"""
    rank = serializers.IntegerField()
    team_id = serializers.IntegerField()
    team_name = serializers.CharField()
    team_slug = serializers.CharField()
    team_logo = serializers.CharField(allow_null=True)
    is_champion = serializers.BooleanField()
    matches_played = serializers.IntegerField()
    wins = serializers.IntegerField()
    losses = serializers.IntegerField()
    ties = serializers.IntegerField(required=False)
    win_ratio = serializers.FloatField()
    
    # Set-based stats (optional)
    sets_won = serializers.IntegerField(required=False)
    sets_lost = serializers.IntegerField(required=False)
    set_ratio = serializers.FloatField(required=False)
    points = serializers.IntegerField(required=False)
    sets_win_percentage = serializers.FloatField(required=False)
    points_per_set = serializers.FloatField(required=False)
    points_conceded_per_set = serializers.FloatField(required=False)
    point_differential_per_set = serializers.FloatField(required=False)
    
    # Point-based stats (optional)
    points_per_game = serializers.FloatField(required=False)
    points_conceded_per_game = serializers.FloatField(required=False)
    point_differential = serializers.FloatField(required=False)
    point_differential_avg = serializers.FloatField(required=False)


class TournamentStatisticsSerializer(serializers.Serializer):
    """Serializer for tournament statistics"""
    teams_count = serializers.IntegerField()
    games_count = serializers.IntegerField()
    games_played = serializers.IntegerField()
    status = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField(allow_null=True)
