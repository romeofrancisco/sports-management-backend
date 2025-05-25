# filepath: c:\Users\ASUS\Desktop\CAPSTONE\backend\sports_management\trainings\serializers.py
from rest_framework import serializers
from .models import MetricUnit, TrainingCategory, TrainingSession, PlayerTraining, TrainingMetric, PlayerMetricRecord
from teams.models import Player, Team, Coach
from datetime import datetime
from django.utils import timezone
import statistics
from django.db.models import Count, Avg, Max, Min
from collections import defaultdict
from datetime import datetime, timedelta

class MetricUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetricUnit
        fields = ["id", "code", "name", "normalization_weight", "description"]


class TrainingCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainingCategory
        fields = ["id", "name", "description"]


class TrainingMetricSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    metric_unit_data = MetricUnitSerializer(source="metric_unit", read_only=True)
    
    class Meta:
        model = TrainingMetric
        fields = ["id", "name", "description", "metric_unit", "metric_unit_data", "category", "category_name", "is_lower_better", "weight"]


class PlayerMetricRecordSerializer(serializers.ModelSerializer):
    metric_name = serializers.CharField(source="metric.name", read_only=True)
    metric_unit_code = serializers.SerializerMethodField()
    metric_unit_name = serializers.SerializerMethodField()
    player_name = serializers.CharField(source="player_training.player.user.get_full_name", read_only=True)
    improvement_from_last = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    improvement_percentage = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    
    def get_metric_unit_code(self, obj):
        return obj.metric.metric_unit.code
        
    def get_metric_unit_name(self, obj):
        return obj.metric.metric_unit.name
    
    class Meta:
        model = PlayerMetricRecord
        fields = ["id", "player_training", "metric", "metric_name", "metric_unit_code", "metric_unit_name", "value", 
                 "player_name", "notes", "recorded_by", "recorded_at",
                 "improvement_from_last", "improvement_percentage"]


class PlayerTrainingSerializer(serializers.ModelSerializer):
    player_name = serializers.CharField(source="player.user.get_full_name", read_only=True)
    session_title = serializers.CharField(source="session.title", read_only=True)
    session_date = serializers.DateField(source="session.date", read_only=True)
    metric_records = PlayerMetricRecordSerializer(many=True, read_only=True)
    
    class Meta:
        model = PlayerTraining
        fields = ["id", "player", "player_name", "session", "session_title", "session_date", 
                  "attendance_status", "notes", "metric_records"]


class TrainingSessionListSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source="team.name", read_only=True)
    coach_name = serializers.CharField(source="coach.user.get_full_name", read_only=True)
    categories_count = serializers.IntegerField(source="categories.count", read_only=True)
    players_count = serializers.SerializerMethodField()
    
    class Meta:
        model = TrainingSession
        fields = ["id", "session_id", "title", "date", "start_time", "end_time", 
                  "team", "team_name", "coach", "coach_name", "location",
                  "training_type", "duration_minutes", "categories_count", "players_count"]
    
    def get_players_count(self, obj):
        return obj.player_records.count()


class TrainingSessionDetailSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source="team.name", read_only=True)
    coach_name = serializers.CharField(source="coach.user.get_full_name", read_only=True)
    categories = TrainingCategorySerializer(many=True, read_only=True)
    player_records = PlayerTrainingSerializer(many=True, read_only=True)
    
    class Meta:
        model = TrainingSession
        fields = ["id", "session_id", "title", "description", "date", "start_time", "end_time", 
                  "team", "team_name", "coach", "coach_name", "location",
                  "training_type", "categories", "notes", "created_at", "updated_at",
                  "duration_minutes", "player_records"]


from trainings.services.metrics_service import MetricService
from trainings.services.progress_service import ProgressService
from trainings.services.performance_service import PerformanceService

class PlayerProgressSerializer(serializers.ModelSerializer):
    metrics_data = serializers.SerializerMethodField()
    player_name = serializers.CharField(source="user.get_full_name")
    team_name = serializers.CharField(source="team.name")
    overall_improvement = serializers.SerializerMethodField()
    recent_improvement = serializers.SerializerMethodField()
    best_performance = serializers.SerializerMethodField()
    training_count = serializers.SerializerMethodField()
    # Remove duplicate performance_analysis field - it's already included in metrics_data
    
    class Meta:
        model = Player
        fields = ["user_id", "player_name", "team", "team_name", "metrics_data", 
                 "overall_improvement", "recent_improvement", "best_performance", 
                 "training_count"]
                 
    def get_metrics_data(self, obj):
        # Get query parameters
        metric_id = self.context.get("request").query_params.get("metric_id", None)
        date_from = self.context.get("request").query_params.get("date_from", None)
        date_to = self.context.get("request").query_params.get("date_to", None)
        
        # Check if player has any training records at all
        if not hasattr(obj, "training_records") or not obj.training_records.exists():
            return []
        
        # Handle "overall" metric specially
        if metric_id == "overall":
            # Get all metric records for overall calculation
            records_query = MetricService.get_player_metric_records(obj, None, date_from, date_to).select_related('metric__metric_unit')
            
            # Create overall metric data structure using ProgressService
            overall_points = ProgressService.calculate_overall_data_points(obj, records_query, date_from, date_to)
            
            if overall_points:
                # Get the overall improvement data to match across views
                overall_improvement = ProgressService.calculate_overall_improvement(obj, date_from, date_to)
                
                overall_metric_data = {
                    "metric_id": "overall",
                    "metric_name": "Overall Performance",
                    "unit": "%",
                    "is_lower_better": False,  # For overall, higher is always better
                    "data_points": overall_points,
                    # Add performance analysis for overall metric
                    "performance_analysis": PerformanceService.calculate_metric_performance_analysis({
                        "metric_id": "overall", 
                        "data_points": overall_points,
                        "is_lower_better": False,  # Overall metric is always "higher is better"
                        "overall_improvement_percentage": overall_improvement["percentage"] if overall_improvement else None
                    }) if len(overall_points) >= 2 else None
                }
                return [overall_metric_data]
            return []
            
        # For specific metrics, get filtered records
        records_query = MetricService.get_player_metric_records(obj, metric_id, date_from, date_to).select_related('metric__metric_unit')
        
        # Group by metric
        metrics_data = {}
        
        # Process individual metrics using MetricService
        metrics_data.update(MetricService.process_metric_records(records_query))

        # Calculate performance analysis for each metric
        for mid, metric_data in metrics_data.items():
            if len(metric_data["data_points"]) >= 2:
                metric_data["performance_analysis"] = PerformanceService.calculate_metric_performance_analysis(metric_data)
                
        # Return only the requested metric data
        if metric_id and metric_id in metrics_data:
            return [metrics_data[metric_id]]
        
        return list(metrics_data.values())
        
    def get_overall_improvement(self, obj):
        """Calculate overall improvement across all metrics"""
        # Check if player has any training records at all
        if not hasattr(obj, "training_records") or not obj.training_records.exists():
            return None
            
        # Get query parameters for date range
        date_from = self.context.get("request").query_params.get("date_from", None)
        date_to = self.context.get("request").query_params.get("date_to", None)
        
        return ProgressService.calculate_overall_improvement(obj, date_from, date_to)
        
    def get_recent_improvement(self, obj):
        """Calculate improvement in the last 30 days across all metrics"""
        # Check if player has any training records at all
        if not hasattr(obj, "training_records") or not obj.training_records.exists():
            return None
            
        # Get query parameters for date range
        date_from = self.context.get("request").query_params.get("date_from", None)
        date_to = self.context.get("request").query_params.get("date_to", None)
        
        return ProgressService.calculate_recent_improvement(obj, date_from, date_to)
    
    def get_best_performance(self, obj):
        """Find best performance in any metric"""
        # Check if player has any training records at all
        if not hasattr(obj, "training_records") or not obj.training_records.exists():
            return None
            
        # Get query parameters for date range
        date_from = self.context.get("request").query_params.get("date_from", None)
        date_to = self.context.get("request").query_params.get("date_to", None)
        
        return ProgressService.find_best_performance(obj, date_from, date_to)
    
    def get_training_count(self, obj):
        """Calculate how many unique training sessions the player has attended"""
        # Check if player has any training records at all
        if not hasattr(obj, "training_records") or not obj.training_records.exists():
            return 0
            
        # Get query parameters for date range
        date_from = self.context.get("request").query_params.get("date_from", None)
        date_to = self.context.get("request").query_params.get("date_to", None)
        
        return ProgressService.count_training_sessions(obj, date_from, date_to)
        
    # The get_performance_analysis method has been removed as it created a duplicate
    # of the performance analysis data already included in the metrics_data array.
    # Performance analysis is now only available through metrics_data[].performance_analysis

class AttendanceAnalyticsSerializer(serializers.Serializer):
    """Serializer for comprehensive attendance analytics"""
    
    # Overall attendance stats
    total_sessions = serializers.IntegerField()
    total_attendance_records = serializers.IntegerField()
    
    # Attendance breakdown
    attendance_breakdown = serializers.DictField()
    attendance_percentage = serializers.DictField()
    
    # Trends
    attendance_trends = serializers.ListField()
    monthly_trends = serializers.ListField()
    
    # Player-specific attendance
    player_attendance_stats = serializers.ListField()
    
    # Session-specific attendance
    session_attendance_history = serializers.ListField()
    
    class Meta:
        fields = '__all__'

class PlayerAttendanceSerializer(serializers.Serializer):
    """Serializer for individual player attendance analytics"""
    
    player_id = serializers.IntegerField()
    player_name = serializers.CharField()
    team_name = serializers.CharField(allow_null=True)
    
    # Attendance stats
    total_sessions = serializers.IntegerField()
    present_count = serializers.IntegerField()
    absent_count = serializers.IntegerField()
    late_count = serializers.IntegerField()
    excused_count = serializers.IntegerField()
    
    # Percentages
    attendance_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    punctuality_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    
    # Trends
    recent_attendance = serializers.ListField()
    attendance_streak = serializers.DictField()
    
    class Meta:
        fields = '__all__'

class AttendanceHeatmapSerializer(serializers.Serializer):
    """Serializer for attendance heatmap data"""
    
    date = serializers.DateField()
    total_players = serializers.IntegerField()
    present_count = serializers.IntegerField()
    absent_count = serializers.IntegerField()
    late_count = serializers.IntegerField()
    excused_count = serializers.IntegerField()
    attendance_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    
    class Meta:
        fields = '__all__'

class AttendanceTrendSerializer(serializers.Serializer):
    """Serializer for attendance trend analysis"""
    
    period = serializers.CharField()  # 'daily', 'weekly', 'monthly'
    date_label = serializers.CharField()
    present_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    absent_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    late_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    excused_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    total_sessions = serializers.IntegerField()
    
    class Meta:
        fields = '__all__'


