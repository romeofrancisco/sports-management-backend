from rest_framework import serializers


class SystemOverviewSerializer(serializers.Serializer):
    total_teams = serializers.IntegerField()
    total_players = serializers.IntegerField()
    total_coaches = serializers.IntegerField()
    total_games = serializers.IntegerField()
    total_leagues = serializers.IntegerField()
    total_sports = serializers.IntegerField()


class RecentActivitySerializer(serializers.Serializer):
    recent_games = serializers.IntegerField()
    recent_training_sessions = serializers.IntegerField()
    recent_player_registrations = serializers.IntegerField()


class DistributionStatsSerializer(serializers.Serializer):
    teams_by_sport = serializers.ListField()
    players_by_sport = serializers.ListField()
    games_by_status = serializers.ListField()


class AdminOverviewSerializer(serializers.Serializer):
    system_overview = SystemOverviewSerializer()
    recent_activity = RecentActivitySerializer()
    distribution_stats = DistributionStatsSerializer()


class TrainingAnalyticsSerializer(serializers.Serializer):
    total_training_records = serializers.IntegerField()
    overall_attendance_rate = serializers.FloatField()


class GameAnalyticsSerializer(serializers.Serializer):
    completed_games = serializers.IntegerField()
    upcoming_games = serializers.IntegerField()
    in_progress_games = serializers.IntegerField()


class TeamStatsSerializer(serializers.Serializer):
    team_name = serializers.CharField()
    wins = serializers.IntegerField()
    losses = serializers.IntegerField()
    win_rate = serializers.FloatField()


class CoachStatsSerializer(serializers.Serializer):
    coach_name = serializers.CharField()
    team_count = serializers.IntegerField()


class AdminAnalyticsSerializer(serializers.Serializer):
    training_analytics = TrainingAnalyticsSerializer()
    game_analytics = GameAnalyticsSerializer()
    top_teams = TeamStatsSerializer(many=True)
    coach_statistics = CoachStatsSerializer(many=True)


class TeamOverviewSerializer(serializers.Serializer):
    total_teams = serializers.IntegerField()
    total_players = serializers.IntegerField()
    recent_training_sessions = serializers.IntegerField()


class TeamAttendanceSerializer(serializers.Serializer):
    team_name = serializers.CharField()
    team_id = serializers.IntegerField()
    attendance_rate = serializers.FloatField()
    total_sessions = serializers.IntegerField()
    total_players = serializers.IntegerField()


class UpcomingGameSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    home_team = serializers.CharField()
    away_team = serializers.CharField()
    date = serializers.DateTimeField()
    location = serializers.CharField()
    is_home = serializers.BooleanField()


class RecentSessionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    date = serializers.DateField()
    team = serializers.CharField()
    attendance_count = serializers.IntegerField()
    total_players = serializers.IntegerField()


class CoachOverviewSerializer(serializers.Serializer):
    team_overview = TeamOverviewSerializer()
    team_attendance = TeamAttendanceSerializer(many=True)
    upcoming_games = UpcomingGameSerializer(many=True)
    recent_training_sessions = RecentSessionSerializer(many=True)


class PlayerProgressSerializer(serializers.Serializer):
    player_id = serializers.IntegerField()
    player_name = serializers.CharField()
    team = serializers.CharField()
    jersey_number = serializers.IntegerField()
    recent_metrics_count = serializers.IntegerField()
    attendance_rate = serializers.FloatField()
    total_sessions = serializers.IntegerField()
    last_training_date = serializers.DateField(allow_null=True)


class CoachPlayerProgressSerializer(serializers.Serializer):
    player_progress = PlayerProgressSerializer(many=True)


class PersonalStatsSerializer(serializers.Serializer):
    attendance_rate = serializers.FloatField()
    total_sessions_last_30_days = serializers.IntegerField()
    attended_sessions = serializers.IntegerField()
    jersey_number = serializers.IntegerField()
    positions = serializers.ListField()
    height = serializers.FloatField(allow_null=True)
    weight = serializers.FloatField(allow_null=True)


class UpcomingSessionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    date = serializers.DateField()
    start_time = serializers.TimeField()
    location = serializers.CharField()


class RecentMetricSerializer(serializers.Serializer):
    metric_name = serializers.CharField()
    value = serializers.FloatField()
    unit = serializers.CharField()
    recorded_at = serializers.DateTimeField()
    session_date = serializers.DateField()


class TeamInfoSerializer(serializers.Serializer):
    name = serializers.CharField()
    sport = serializers.CharField()
    total_players = serializers.IntegerField()
    coach = serializers.CharField()


class PlayerOverviewSerializer(serializers.Serializer):
    personal_stats = PersonalStatsSerializer()
    upcoming_sessions = UpcomingSessionSerializer(many=True)
    upcoming_games = UpcomingGameSerializer(many=True)
    recent_metrics = RecentMetricSerializer(many=True)
    team_info = TeamInfoSerializer(allow_null=True)


class ProgressSummarySerializer(serializers.Serializer):
    total_metrics_recorded = serializers.IntegerField()
    unique_metrics = serializers.IntegerField()
    training_sessions_attended = serializers.IntegerField()
    total_training_sessions = serializers.IntegerField()


class MetricTrendDataSerializer(serializers.Serializer):
    value = serializers.FloatField()
    date = serializers.DateField()
    unit = serializers.CharField()


class PlayerProgressDetailSerializer(serializers.Serializer):
    progress_summary = serializers.DictField()
    metric_trends = serializers.DictField()
