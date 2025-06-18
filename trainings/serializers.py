from rest_framework import serializers
from .models import MetricUnit, TrainingCategory, TrainingSession, PlayerTraining, TrainingMetric, PlayerMetricRecord
from teams.models import Player, Team
from datetime import datetime
from django.utils import timezone
import statistics
from django.db.models import Count, Avg, Max, Min
from collections import defaultdict
from datetime import datetime, timedelta

class MetricUnitSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True)
    
    class Meta:
        model = MetricUnit
        fields = ["id", "code", "name", "normalization_weight", "description", "is_default", "created_by", "created_by_name"]
        read_only_fields = ["created_by", "created_by_name"]


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
    session_start_time = serializers.TimeField(source="session.start_time", read_only=True)
    session_end_time = serializers.TimeField(source="session.end_time", read_only=True)
    session_location = serializers.CharField(source="session.location", read_only=True)
    session_status = serializers.CharField(source="session.status", read_only=True)
    session_description = serializers.CharField(source="session.description", read_only=True)
    metric_records = PlayerMetricRecordSerializer(many=True, read_only=True)
    assigned_metrics = TrainingMetricSerializer(many=True, read_only=True)
    metrics_completion_status = serializers.SerializerMethodField()
    can_record_metrics = serializers.SerializerMethodField()
    # Add nested player data for frontend compatibility
    player = serializers.SerializerMethodField()
    
    def get_player(self, obj):
        """Return enhanced player data with profile information"""
        user = obj.player.user        
        # Get profile URL with full absolute URI when request is available
        profile_url = None
        if user.profile:
            request = self.context.get('request')
            if request:
                profile_url = request.build_absolute_uri(user.profile.url)
            else:
                profile_url = user.profile.url
        
        return {
            'id': user.id,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'full_name': user.get_full_name(),
            'profile': profile_url,
        }
    
    def get_metrics_completion_status(self, obj):
        """Calculate completion status of assigned metrics"""
        assigned_metrics = obj.assigned_metrics.all()
        recorded_metrics = obj.metric_records.all()
        
        if not assigned_metrics.exists():
            return {
                'total_assigned': 0,
                'total_recorded': 0,
                'completion_percentage': 0,
                'status': 'no_metrics'
            }
        
        total_assigned = assigned_metrics.count()
        # Count metrics that have been recorded (have a value)
        recorded_metric_ids = set(
            recorded_metrics.filter(value__isnull=False).values_list('metric_id', flat=True)
        )
        assigned_metric_ids = set(assigned_metrics.values_list('id', flat=True))
        total_recorded = len(recorded_metric_ids.intersection(assigned_metric_ids))
        
        completion_percentage = (total_recorded / total_assigned * 100) if total_assigned > 0 else 0
        
        # Determine status based on session status and attendance
        session_status = obj.session.status
        attendance_status = obj.attendance_status
        
        # If session is completed and player was not present, mark as missed
        if session_status == 'completed':
            if attendance_status in ['absent', 'excused'] or (attendance_status == 'pending' and total_recorded == 0):
                status = 'missed_training'
            elif total_recorded == 0:
                status = 'missed_training'  # Completed session but no metrics recorded
            elif total_recorded == total_assigned:
                status = 'completed'
            else:
                status = 'partially_completed'
        else:
            # For non-completed sessions, use the original logic
            if total_recorded == 0:
                status = 'not_started'
            elif total_recorded == total_assigned:
                status = 'completed'
            else:
                status = 'in_progress'
            
        return {
            'total_assigned': total_assigned,
            'total_recorded': total_recorded,
            'completion_percentage': round(completion_percentage, 1),
            'status': status
        }
    
    def get_can_record_metrics(self, obj):
        """Check if metrics can be recorded for this session"""
        return obj.session.can_record_metrics()
    
    class Meta:
        model = PlayerTraining
        fields = ["id", "player", "player_name", "session", "session_title", "session_date", 
                  "session_start_time", "session_end_time", "session_location", "session_status",
                  "session_description", "attendance_status", "notes", "metric_records", 
                  "assigned_metrics", "metrics_completion_status", "can_record_metrics"]


class TrainingSessionListSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source="team.name", read_only=True)
    categories_count = serializers.IntegerField(source="categories.count", read_only=True)
    players_count = serializers.SerializerMethodField()
    auto_status = serializers.CharField(source="get_auto_status", read_only=True)
    can_manage_attendance = serializers.BooleanField(read_only=True)
    can_configure_metrics = serializers.BooleanField(read_only=True)
    can_record_metrics = serializers.BooleanField(read_only=True)
    player_attendance_status = serializers.SerializerMethodField()
    
    class Meta:
        model = TrainingSession
        fields = ["id", "session_id", "title", "date", "start_time", "end_time", 
                  "team", "team_name", "location", "status", "auto_status", 
                  "duration_minutes", "categories_count", "players_count", 
                  "can_manage_attendance", "can_configure_metrics", "can_record_metrics",
                  "player_attendance_status"]
    
    def get_players_count(self, obj):
        return obj.player_records.count()
        
    def get_player_attendance_status(self, obj):
        """Get the current user's attendance status for this session"""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
            
        # Only return attendance status for players
        if not hasattr(request.user, 'player_profile'):
            return None
            
        try:
            player_training = obj.player_records.get(player=request.user.player_profile)
            return player_training.attendance_status
        except PlayerTraining.DoesNotExist:
            return 'pending'  # Default status if no record exists


class TrainingSessionDetailSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source="team.name", read_only=True)
    categories = TrainingCategorySerializer(many=True, read_only=True)
    player_records = PlayerTrainingSerializer(many=True, read_only=True)
    auto_status = serializers.CharField(source="get_auto_status", read_only=True)
    can_manage_attendance = serializers.BooleanField(read_only=True)
    can_configure_metrics = serializers.BooleanField(read_only=True)
    can_record_metrics = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = TrainingSession
        fields = ["id", "session_id", "title", "description", "date", "start_time", "end_time", 
                  "team", "team_name", "location", "status", "auto_status", "categories", 
                  "notes", "created_at", "updated_at", "duration_minutes", "player_records",
                  "can_manage_attendance", "can_configure_metrics", "can_record_metrics"]


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


