# filepath: c:\Users\ASUS\Desktop\CAPSTONE\backend\sports_management\trainings\serializers.py
from rest_framework import serializers
from .models import MetricUnit, TrainingCategory, TrainingSession, PlayerTraining, TrainingMetric, PlayerMetricRecord
from teams.models import Player, Team, Coach
from datetime import datetime
from django.utils import timezone
import statistics
from django.db.models import Count, Avg, Max, Min

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
        
        # Early optimization: If requesting "overall" or no specific metric, only process overall                if metric_id == "overall" or not metric_id:
                    # Get necessary records for overall calculation only
            records_query = MetricService.get_player_metric_records(obj, None, date_from, date_to).select_related('metric__metric_unit')
            metrics_data = {}
            
            # Create overall metric data structure using ProgressService
            overall_points = ProgressService.calculate_overall_data_points(obj, records_query, date_from, date_to)
            
            if overall_points:
                # Get the overall improvement data to match across views
                overall_improvement = ProgressService.calculate_overall_improvement(obj, date_from, date_to)
                
                metrics_data["overall"] = {
                    "metric_id": "overall",
                    "metric_name": "Overall Performance",
                    "unit": "%",
                    "is_lower_better": False,  # For overall, higher is always better
                    "data_points": overall_points,
                    # Add performance analysis directly for this case with consistent percentage
                    "performance_analysis": PerformanceService.calculate_metric_performance_analysis({
                        "metric_id": "overall", 
                        "data_points": overall_points,
                        "is_lower_better": False,  # Overall metric is always "higher is better"
                        # Pass the overall improvement percentage for consistency
                        "overall_improvement_percentage": overall_improvement["percentage"] if overall_improvement else None
                        # Note: Explicitly including is_lower_better to avoid KeyError (see performance-service-fix.md)
                    }) if len(overall_points) >= 2 else None
                }
                return [metrics_data["overall"]]
            return []
            
        # For specific metrics, get filtered records
        records_query = MetricService.get_player_metric_records(obj, metric_id, date_from, date_to).select_related('metric__metric_unit')
        
        # Group by metric
        metrics_data = {}
        
        # Process individual metrics using MetricService
        metrics_data.update(MetricService.process_metric_records(records_query))

        # Calculate performance analysis for each metric
        for metric_id, metric_data in metrics_data.items():
            if len(metric_data["data_points"]) >= 2:
                metric_data["performance_analysis"] = PerformanceService.calculate_metric_performance_analysis(metric_data)
                
        # Return only the requested metric data
        if metric_id in metrics_data:
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

class TeamTrainingAnalyticsSerializer(serializers.ModelSerializer):
    attendance_rate = serializers.SerializerMethodField()
    training_sessions_count = serializers.SerializerMethodField()
    player_metrics_summary = serializers.SerializerMethodField()
    
    class Meta:
        model = Team
        fields = ["id", "name", "attendance_rate", "training_sessions_count", "player_metrics_summary"]
        
    def get_attendance_rate(self, obj):
        """Calculate attendance rate for the team"""
        # Get query parameters for date range
        date_from = self.context.get("request").query_params.get("date_from", None)
        date_to = self.context.get("request").query_params.get("date_to", None)
        
        # Get all sessions for this team
        sessions_query = TrainingSession.objects.filter(team=obj)
        
        # Apply date filters if provided
        if date_from:
            sessions_query = sessions_query.filter(date__gte=date_from)
        if date_to:
            sessions_query = sessions_query.filter(date__lte=date_to)
            
        # Get attendance records for these sessions
        attendance_records = PlayerTraining.objects.filter(
            session__in=sessions_query
        )
        
        total_attendance_records = attendance_records.count()
        
        if total_attendance_records == 0:
            return {
                "present_rate": 0,
                "absent_rate": 0,
                "late_rate": 0,
                "excused_rate": 0
            }
        
        # Count different attendance statuses
        present_count = attendance_records.filter(attendance_status="present").count()
        absent_count = attendance_records.filter(attendance_status="absent").count()
        late_count = attendance_records.filter(attendance_status="late").count()
        excused_count = attendance_records.filter(attendance_status="excused").count()
        
        return {
            "present_rate": round(present_count / total_attendance_records * 100, 2),
            "absent_rate": round(absent_count / total_attendance_records * 100, 2),
            "late_rate": round(late_count / total_attendance_records * 100, 2),
            "excused_rate": round(excused_count / total_attendance_records * 100, 2)
        }
    
    def get_training_sessions_count(self, obj):
        """Count training sessions for this team"""
        # Get query parameters for date range
        date_from = self.context.get("request").query_params.get("date_from", None)
        date_to = self.context.get("request").query_params.get("date_to", None)
        
        # Get all sessions for this team
        sessions_query = TrainingSession.objects.filter(team=obj)
        
        # Apply date filters if provided
        if date_from:
            sessions_query = sessions_query.filter(date__gte=date_from)
        if date_to:
            sessions_query = sessions_query.filter(date__lte=date_to)
            
        return sessions_query.count()
    
    def get_player_metrics_summary(self, obj):
        """Get summary of player metrics improvements for the team"""
        # Get query parameters
        metric_id = self.context.get("request").query_params.get("metric_id", None)
        date_from = self.context.get("request").query_params.get("date_from", None)
        date_to = self.context.get("request").query_params.get("date_to", None)
        
        if not metric_id:
            return []
        
        # Get all players in the team with a prefetch for user data to avoid N+1 queries
        players = obj.players.all().select_related('user')
        
        # Build filter conditions dynamically for more efficient querying
        filter_dict = {
            'player_training__player__in': players,
            'metric_id': metric_id
        }
        
        if date_from:
            filter_dict['player_training__session__date__gte'] = date_from
        if date_to:
            filter_dict['player_training__session__date__lte'] = date_to
            
        # Fetch all relevant records in a single query with all needed relations
        records = PlayerMetricRecord.objects.filter(
            **filter_dict
        ).select_related(
            "player_training__player", 
            "player_training__player__user", 
            "player_training__session",
            "metric",
            "metric__metric_unit"
        )
        
        # Group records by player for efficient processing
        player_records = {}
        for record in records:
            player_id = record.player_training.player.id
            if player_id not in player_records:
                player_records[player_id] = []
            player_records[player_id].append(record)
        
        # Process each player's records
        players_data = []
        for player in players:
            if player.id not in player_records or not player_records[player.id]:
                continue
                
            # Sort player records by date
            player_recs = sorted(player_records[player.id], 
                                key=lambda r: r.player_training.session.date)
            
            # Get first and last record in the period to calculate improvement
            first_record = player_recs[0]
            last_record = player_recs[-1]
            
            if first_record and last_record:
                # Calculate raw improvement
                raw_diff = last_record.value - first_record.value
                
                # For metrics where lower is better (like time), negate the difference
                if first_record.metric.is_lower_better:
                    improvement = -raw_diff
                else:
                    improvement = raw_diff
                
                # Calculate percentage improvement if initial value is not zero
                if first_record.value != 0:
                    percentage = (raw_diff / first_record.value) * 100
                    if first_record.metric.is_lower_better:
                        percentage = -percentage
                else:
                    percentage = None
                    
                players_data.append({
                    "player_id": player.user_id,
                    "player_name": f"{player.user.first_name} {player.user.last_name}",
                    "first_value": first_record.value,
                    "last_value": last_record.value,
                    "improvement": improvement,
                    "improvement_percentage": percentage
                })
                
        return players_data
