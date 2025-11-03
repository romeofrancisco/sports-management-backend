from rest_framework import serializers
from .models import League, Season
from sports.serializers import SportSerializer
from teams.models import Team


class LeagueSerializer(serializers.ModelSerializer):
    sport = SportSerializer()
    teams_count = serializers.SerializerMethodField()
    games_count = serializers.SerializerMethodField()
    season = serializers.SerializerMethodField()
    seasons_count = serializers.SerializerMethodField()

    class Meta:
        model = League
        fields = [
            "id",
            "name",
            "division",
            "logo",
            "sport",
            "teams_count",
            "games_count",
            "season",
            "seasons_count",
        ]
        read_only_fields = ["created_at"]

    def get_teams_count(self, obj):
        """Get total number of teams across all seasons"""
        # Get all unique teams across all seasons
        all_teams = set()
        for season in obj.seasons.all():
            all_teams.update(season.teams.all())
        return len(all_teams)

    def get_games_count(self, obj):
        """Get total number of games across all seasons"""
        total_games = 0
        for season in obj.seasons.all():
            total_games += season.games_count
        return total_games

    def get_season(self, obj):
        """Get current season name"""
        # Try to get the most recent ongoing season, otherwise the most recent season
        current_season = obj.seasons.filter(status="ongoing").first()
        if not current_season:
            current_season = obj.seasons.order_by("-start_date").first()

        if current_season:
            return current_season.name
        return None

    def get_seasons_count(self, obj):
        """Get total number of seasons for this league"""
        return obj.seasons.count()


class LeagueWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = League
        fields = ["id", "division", "name", "logo", "sport"]
        read_only_fields = ["created_at"]


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
    bracket_type = serializers.CharField(source='bracket.elimination_type', read_only=True, allow_null=True)
    games_count = serializers.IntegerField(read_only=True)
    games_played = serializers.IntegerField(read_only=True)
    avg_points_per_game = serializers.FloatField(read_only=True)

    class Meta:
        model = Season
        fields = [
            "id",
            "name",
            "league",
            "status",
            "start_date",
            "end_date",
            "has_bracket",
            "games_count",
            "games_played",
            "avg_points_per_game",
            "bracket_type",
            "teams",
            "is_recorded",
            "league_name",
            "teams_list",
        ]
        read_only_fields = ["league", "team_lists"]
        extra_kwargs = {"teams": {"write_only": True}}

    def validate(self, data):
        start = data.get("start_date")
        end = data.get("end_date")
        teams = data.get("teams", [])
        

        # Allow end_date to be None or missing
        if start and end:
            if start >= end:
                raise serializers.ValidationError(
                    {"end_date": "End date must be after start date."}
                )
        
        # Validate that all teams have the same division as the league
        if teams and hasattr(self, 'instance') and self.instance:
            league = self.instance.league
            for team in teams:
                if team.division != league.division:
                    raise serializers.ValidationError({
                        "teams": f"Team '{team.name}' has division '{team.division}' but league '{league.name}' requires '{league.division}' division."
                    })
        elif teams and 'league' in self.context:
            # For creation, get league from context
            league = self.context['league']
            for team in teams:
                if team.division != league.division:
                    raise serializers.ValidationError({
                        "teams": f"Team '{team.name}' has division '{team.division}' but league '{league.name}' requires '{league.division}' division."
                    })
                    
        return data

    def get_has_bracket(self, obj):
        return hasattr(obj, "bracket")

    def get_league_name(self, obj):
        return obj.league.name

    def get_teams_list(self, obj):
        request = self.context.get("request")
        return TeamSerializer(
            obj.teams.all(), many=True, context={"request": request}
        ).data


class TeamStandingsSerializer(serializers.ModelSerializer):
    standings = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = ["id", "name", "logo", "standings"]

    def get_logo(self, obj):
        request = self.context.get("request")
        if obj.logo:
            return request.build_absolute_uri(obj.logo.url)
        return None

    def get_standings(self, obj):
        return self.context["standings_data"].get(obj.id, {})


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
    champion = serializers.CharField(allow_null=True)
    teams_count = serializers.IntegerField()
    games_count = serializers.IntegerField()
    avg_points_per_game = serializers.FloatField()
    top_team = serializers.CharField(allow_null=True)
