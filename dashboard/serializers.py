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
    # Optional monthly trend payload for charts: { labels: [...], values: [...] }
    monthly_trend = serializers.DictField(required=False)
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
    date = serializers.DateField()
    time = serializers.TimeField(allow_null=True)
    location = serializers.CharField()
    is_home = serializers.BooleanField()


class UpcomingTrainingSessionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    date = serializers.DateField()
    start_time = serializers.TimeField(allow_null=True)
    location = serializers.CharField()
    team = serializers.CharField()


class RecentGameSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    home_team = serializers.CharField()
    away_team = serializers.CharField()
    date = serializers.DateField()
    time = serializers.TimeField(allow_null=True)
    location = serializers.CharField()
    home_team_score = serializers.IntegerField()
    away_team_score = serializers.IntegerField()
    is_home = serializers.BooleanField()
    result = serializers.CharField()  # "win", "loss", or "draw"


class RecentSessionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    date = serializers.DateField()
    location = serializers.CharField()
    team = serializers.CharField()
    attendance_count = serializers.IntegerField()
    total_players = serializers.IntegerField()


class CoachOverviewSerializer(serializers.Serializer):
    team_overview = TeamOverviewSerializer()
    team_attendance = TeamAttendanceSerializer(many=True)
    upcoming_games = UpcomingGameSerializer(many=True)
    recent_training_sessions = RecentSessionSerializer(many=True)
    upcoming_training_sessions = UpcomingTrainingSessionSerializer(many=True)
    recent_games = RecentGameSerializer(many=True)


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


# New serializers for summary services

class HealthIndicatorSerializer(serializers.Serializer):
    health_score = serializers.FloatField()
    health_status = serializers.CharField()
    indicators = serializers.DictField()
    alerts = serializers.ListField()


class TrendDataSerializer(serializers.Serializer):
    period_days = serializers.IntegerField()
    daily_activity = serializers.ListField()
    weekly_trends = serializers.ListField()


class PerformanceIndicatorSerializer(serializers.Serializer):
    training_attendance_rate = serializers.FloatField()
    game_completion_rate = serializers.FloatField()
    league_activity_rate = serializers.FloatField()
    user_engagement_rate = serializers.FloatField()


class DashboardSummarySerializer(serializers.Serializer):
    system_overview = serializers.DictField()
    health_indicators = HealthIndicatorSerializer()
    user_activity_summary = serializers.DictField()
    performance_indicators = PerformanceIndicatorSerializer()
    trend_data = TrendDataSerializer()
    distribution_stats = serializers.DictField()


# Training Summary Serializers

class TrainingOverviewSerializer(serializers.Serializer):
    total_trainings = serializers.IntegerField()
    active_trainings = serializers.IntegerField()
    recent_sessions = serializers.IntegerField()
    attendance_rate = serializers.FloatField()
    unique_participants = serializers.IntegerField()
    avg_sessions_per_training = serializers.FloatField()
    period_days = serializers.IntegerField()


class TrainingTrendsSerializer(serializers.Serializer):
    daily_sessions = serializers.ListField()
    weekly_attendance = serializers.ListField()
    sport_distribution = serializers.ListField()
    period_days = serializers.IntegerField()


class TrainingPerformanceSerializer(serializers.Serializer):
    top_trainings = serializers.ListField()
    coach_performance = serializers.ListField()
    completion_stats = serializers.DictField()
    period_days = serializers.IntegerField()


class TrainingSummarySerializer(serializers.Serializer):
    training_overview = TrainingOverviewSerializer()
    training_trends = TrainingTrendsSerializer()
    training_performance = TrainingPerformanceSerializer()
    health_indicators = HealthIndicatorSerializer()


# League Summary Serializers

class LeagueOverviewSerializer(serializers.Serializer):
    total_leagues = serializers.IntegerField()
    active_leagues = serializers.IntegerField()
    current_seasons = serializers.IntegerField()
    recent_matches = serializers.IntegerField()
    completed_matches = serializers.IntegerField()
    completion_rate = serializers.FloatField()
    active_teams = serializers.IntegerField()
    total_participants = serializers.IntegerField()
    period_days = serializers.IntegerField()


class LeagueTrendsSerializer(serializers.Serializer):
    daily_matches = serializers.ListField()
    weekly_activity = serializers.ListField()
    league_distribution = serializers.ListField()
    season_progression = serializers.ListField()
    period_days = serializers.IntegerField()


class LeaguePerformanceSerializer(serializers.Serializer):
    top_leagues = serializers.ListField()
    team_performance = serializers.ListField()
    engagement_stats = serializers.DictField()
    period_days = serializers.IntegerField()


class LeagueSummarySerializer(serializers.Serializer):
    league_overview = LeagueOverviewSerializer()
    league_trends = LeagueTrendsSerializer()
    league_performance = LeaguePerformanceSerializer()
    health_indicators = HealthIndicatorSerializer()


# Game Summary Serializers

class GameOverviewSerializer(serializers.Serializer):
    total_games = serializers.IntegerField()
    recent_games = serializers.IntegerField()
    completed_games = serializers.IntegerField()
    upcoming_games = serializers.IntegerField()
    completion_rate = serializers.FloatField()
    total_participations = serializers.IntegerField()
    unique_participants = serializers.IntegerField()
    avg_duration = serializers.FloatField()
    active_teams = serializers.IntegerField()
    period_days = serializers.IntegerField()


class GameTrendsSerializer(serializers.Serializer):
    daily_games = serializers.ListField()
    weekly_activity = serializers.ListField()
    sport_distribution = serializers.ListField()
    game_type_distribution = serializers.ListField()
    period_days = serializers.IntegerField()


class GamePerformanceSerializer(serializers.Serializer):
    top_players = serializers.ListField()
    team_performance = serializers.ListField()
    game_statistics = serializers.DictField()
    score_distribution = serializers.DictField()
    period_days = serializers.IntegerField()


class GameSummarySerializer(serializers.Serializer):
    game_overview = GameOverviewSerializer()
    game_trends = GameTrendsSerializer()
    game_performance = GamePerformanceSerializer()
    health_indicators = HealthIndicatorSerializer()


# Analytics Serializers

class EngagementAnalyticsSerializer(serializers.Serializer):
    top_engaged_users = serializers.ListField()
    module_activity = serializers.DictField()
    daily_engagement = serializers.ListField()
    total_engaged_users = serializers.IntegerField()
    period_days = serializers.IntegerField()


class PerformanceComparisonSerializer(serializers.Serializer):
    sport_performance = serializers.ListField()
    team_performance = serializers.ListField()
    role_activity = serializers.DictField()
    period_days = serializers.IntegerField()


class ChartDatasetSerializer(serializers.Serializer):
    label = serializers.CharField()
    data = serializers.ListField()
    color = serializers.CharField()


class ChartDataSerializer(serializers.Serializer):
    type = serializers.CharField()
    data = serializers.ListField()
    labels = serializers.ListField(required=False)
    datasets = ChartDatasetSerializer(many=True, required=False)
    week_labels = serializers.ListField(required=False)
    day_labels = serializers.ListField(required=False)


class AnalyticsSerializer(serializers.Serializer):
    engagement_analytics = EngagementAnalyticsSerializer()
    performance_comparison = PerformanceComparisonSerializer()
    chart_data = ChartDataSerializer()


# Chart Data Serializers for Summary Services
class WeeklyDataItemSerializer(serializers.Serializer):
    week_start = serializers.CharField()
    week_end = serializers.CharField()
    sessions_count = serializers.IntegerField()
    participants = serializers.IntegerField()
    hours_trained = serializers.FloatField()


class WeeklyTrendsSerializer(serializers.Serializer):
    weekly_data = WeeklyDataItemSerializer(many=True)
    trend_percentage = serializers.FloatField()
    weeks_analyzed = serializers.IntegerField()


class DailyActivityItemSerializer(serializers.Serializer):
    date = serializers.CharField()
    trainings = serializers.IntegerField()
    games = serializers.IntegerField()
    total = serializers.IntegerField()


class EngagementAnalyticsSerializer(serializers.Serializer):
    module_activity = serializers.DictField()
    daily_activity = DailyActivityItemSerializer(many=True)
    user_engagement = serializers.ListField()
    total_engaged_users = serializers.IntegerField()
    period_days = serializers.IntegerField()


class SportComparisonItemSerializer(serializers.Serializer):
    sport_name = serializers.CharField()
    total_games = serializers.IntegerField()
    total_teams = serializers.IntegerField()
    total_leagues = serializers.IntegerField()
    active_players = serializers.IntegerField()


class TeamComparisonItemSerializer(serializers.Serializer):
    team_name = serializers.CharField()
    games_played = serializers.IntegerField()
    games_won = serializers.IntegerField()
    win_rate = serializers.FloatField()
    avg_home_score = serializers.FloatField()
    avg_away_score = serializers.FloatField()
    player_count = serializers.IntegerField()


class ComparativeAnalyticsSerializer(serializers.Serializer):
    sport_comparison = SportComparisonItemSerializer(many=True)
    team_comparison = TeamComparisonItemSerializer(many=True)
    league_comparison = serializers.ListField()
    monthly_comparison = serializers.ListField()


class ScoreDistributionItemSerializer(serializers.Serializer):
    range = serializers.CharField()
    count = serializers.IntegerField()


class GameStatisticsSerializer(serializers.Serializer):
    score_distribution = ScoreDistributionItemSerializer(many=True)
    game_types = serializers.ListField()
    status_distribution = serializers.ListField()
    team_activity = serializers.ListField()


class ActivityHeatmapItemSerializer(serializers.Serializer):
    date = serializers.CharField()
    day_of_week = serializers.CharField()
    games = serializers.IntegerField()
    trainings = serializers.IntegerField()
    total_activity = serializers.IntegerField()
    intensity = serializers.CharField()


class ActivityHeatmapSerializer(serializers.Serializer):
    heatmap_data = ActivityHeatmapItemSerializer(many=True)
    day_of_week_analysis = serializers.DictField()
    days_analyzed = serializers.IntegerField()


class PerformanceMetricsSerializer(serializers.Serializer):
    game_performance = serializers.DictField()
    training_performance = serializers.DictField()
    league_performance = serializers.DictField()
    system_metrics = serializers.DictField()


class GrowthDataItemSerializer(serializers.Serializer):
    month = serializers.CharField()
    new_users = serializers.IntegerField()
    new_teams = serializers.IntegerField()
    new_leagues = serializers.IntegerField()
    games_conducted = serializers.IntegerField()
    training_sessions = serializers.IntegerField()


class GrowthAnalyticsSerializer(serializers.Serializer):
    monthly_growth = GrowthDataItemSerializer(many=True)
    growth_rates = serializers.DictField()
    months_analyzed = serializers.IntegerField()


class RecentActivityItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    type = serializers.CharField()
    date = serializers.CharField()
    title = serializers.CharField()
    status = serializers.CharField()
    sport = serializers.CharField()
    location = serializers.CharField()


class HealthIndicatorSerializer(serializers.Serializer):
    recent_activity_level = serializers.CharField()
    recent_sessions_count = serializers.IntegerField()
    data_quality_score = serializers.FloatField()
    active_players = serializers.IntegerField()
    monthly_sessions = serializers.IntegerField()
    system_status = serializers.CharField()


# Comprehensive Summary Response Serializers
class TrainingSummaryResponseSerializer(serializers.Serializer):
    overview = serializers.DictField()
    weekly_trends = WeeklyTrendsSerializer()
    performance_indicators = serializers.DictField()
    recent_activity = serializers.DictField()
    health_indicators = HealthIndicatorSerializer()


class GameSummaryResponseSerializer(serializers.Serializer):
    overview = serializers.DictField()
    weekly_trends = serializers.DictField()
    performance_indicators = serializers.DictField()
    statistics_summary = GameStatisticsSerializer()
    recent_activity = serializers.DictField()
    health_indicators = serializers.DictField()


class LeagueSummaryResponseSerializer(serializers.Serializer):
    overview = serializers.DictField()
    performance_indicators = serializers.DictField()
    recent_activity = serializers.DictField()
    health_indicators = serializers.DictField()


class AnalyticsSummaryResponseSerializer(serializers.Serializer):
    engagement_analytics = EngagementAnalyticsSerializer()
    comparative_analytics = ComparativeAnalyticsSerializer()
    growth_analytics = GrowthAnalyticsSerializer()
    activity_heatmap = ActivityHeatmapSerializer()
    performance_analytics = PerformanceMetricsSerializer()
