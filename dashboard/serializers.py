from rest_framework import serializers


class SystemOverviewSerializer(serializers.Serializer):
    total_teams = serializers.IntegerField()
    total_players = serializers.IntegerField()
    total_coaches = serializers.IntegerField()
    total_games = serializers.IntegerField()
    total_leagues = serializers.IntegerField()
    total_sports = serializers.IntegerField()
    unassigned_players = serializers.IntegerField()
    coaches_without_teams = serializers.IntegerField()
    avg_players_per_team = serializers.FloatField()


class UserActivitySerializer(serializers.Serializer):
    active_users_today = serializers.IntegerField()
    active_users_week = serializers.IntegerField()
    new_users_month = serializers.IntegerField()
    new_users_week = serializers.IntegerField()


class RecentActivitySerializer(serializers.Serializer):
    games_this_month = serializers.IntegerField()
    completed_games_month = serializers.IntegerField()
    training_sessions_month = serializers.IntegerField()
    games_scheduled = serializers.IntegerField()
    upcoming_trainings = serializers.IntegerField()


class SystemHealthSerializer(serializers.Serializer):
    teams_without_coaches = serializers.IntegerField()
    teams_with_few_players = serializers.IntegerField()
    unassigned_players = serializers.IntegerField()


class GenderStatsSerializer(serializers.Serializer):
    male_players = serializers.IntegerField()
    female_players = serializers.IntegerField()
    male_teams = serializers.IntegerField()
    female_teams = serializers.IntegerField()
    players_by_gender_sport = serializers.ListField()
    teams_by_division_sport = serializers.ListField()


class DistributionStatsSerializer(serializers.Serializer):
    teams_by_sport = serializers.ListField()
    players_by_sport = serializers.ListField()
    active_leagues = serializers.ListField()
    gender_stats = GenderStatsSerializer()


class AdminOverviewSerializer(serializers.Serializer):
    system_overview = SystemOverviewSerializer()
    user_activity = UserActivitySerializer()
    recent_activity = RecentActivitySerializer()
    system_health = SystemHealthSerializer()
    distribution_stats = DistributionStatsSerializer()
    analytics = serializers.DictField()  # Analytics data for System Performance Summary
    insights = serializers.DictField()   # Insights data for System Performance Summary


class TrainingAnalyticsSerializer(serializers.Serializer):
    total_training_records = serializers.IntegerField()
    overall_attendance_rate = serializers.FloatField()
    monthly_sessions = serializers.IntegerField()
    training_trend = serializers.CharField()
    active_players_month = serializers.IntegerField()


class GameAnalyticsSerializer(serializers.Serializer):
    completed_games = serializers.IntegerField()
    scheduled_games = serializers.IntegerField()
    in_progress_games = serializers.IntegerField()
    completion_rate_month = serializers.FloatField()
    recent_games_total = serializers.IntegerField()


class PerformanceAnalyticsSerializer(serializers.Serializer):
    top_teams = serializers.ListField()
    team_utilization_rate = serializers.FloatField()
    teams_active_month = serializers.IntegerField()


class CoachAnalyticsSerializer(serializers.Serializer):
    coach_id = serializers.IntegerField()
    coach_name = serializers.CharField()
    team_count = serializers.IntegerField()
    total_players = serializers.IntegerField()
    recent_trainings = serializers.IntegerField()
    attendance_rate = serializers.FloatField()
    effectiveness_score = serializers.FloatField()


class SystemHealthMetricsSerializer(serializers.Serializer):
    league_activity_rate = serializers.FloatField()
    active_leagues = serializers.IntegerField()
    total_leagues = serializers.IntegerField()


class GrowthMetricsSerializer(serializers.Serializer):
    new_teams_month = serializers.IntegerField()
    new_players_month = serializers.IntegerField()
    growth_trend = serializers.CharField()


class AdminAnalyticsSerializer(serializers.Serializer):
    training_analytics = TrainingAnalyticsSerializer()
    game_analytics = GameAnalyticsSerializer()
    performance_analytics = PerformanceAnalyticsSerializer()
    coach_analytics = CoachAnalyticsSerializer(many=True)
    system_health = SystemHealthMetricsSerializer()
    growth_metrics = GrowthMetricsSerializer()


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
    overall_improvement = serializers.DictField(allow_null=True)
    recent_improvement = serializers.DictField(allow_null=True)


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
