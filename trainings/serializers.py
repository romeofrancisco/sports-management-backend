from rest_framework import serializers
from .models import TrainingCategory, TrainingSession, PlayerTraining, TrainingMetric, PlayerMetricRecord
from teams.models import Player, Team, Coach

class TrainingCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainingCategory
        fields = ['id', 'name', 'description']


class TrainingMetricSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    
    class Meta:
        model = TrainingMetric
        fields = ['id', 'name', 'description', 'unit', 'category', 'category_name', 'is_lower_better']


class PlayerMetricRecordSerializer(serializers.ModelSerializer):
    metric_name = serializers.CharField(source='metric.name', read_only=True)
    metric_unit = serializers.CharField(source='metric.unit', read_only=True)
    player_name = serializers.CharField(source='player_training.player.user.get_full_name', read_only=True)
    improvement_from_last = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    improvement_percentage = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = PlayerMetricRecord
        fields = ['id', 'player_training', 'metric', 'metric_name', 'metric_unit', 'value', 
                 'player_name', 'notes', 'recorded_by', 'recorded_at',
                 'improvement_from_last', 'improvement_percentage']


class PlayerTrainingSerializer(serializers.ModelSerializer):
    player_name = serializers.CharField(source='player.user.get_full_name', read_only=True)
    session_title = serializers.CharField(source='session.title', read_only=True)
    session_date = serializers.DateField(source='session.date', read_only=True)
    metric_records = PlayerMetricRecordSerializer(many=True, read_only=True)
    
    class Meta:
        model = PlayerTraining
        fields = ['id', 'player', 'player_name', 'session', 'session_title', 'session_date', 
                  'attendance_status', 'notes', 'metric_records']


class TrainingSessionListSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source='team.name', read_only=True)
    coach_name = serializers.CharField(source='coach.user.get_full_name', read_only=True)
    categories_count = serializers.IntegerField(source='categories.count', read_only=True)
    players_count = serializers.SerializerMethodField()
    
    class Meta:
        model = TrainingSession
        fields = ['id', 'session_id', 'title', 'date', 'start_time', 'end_time', 
                  'team', 'team_name', 'coach', 'coach_name', 'location',
                  'training_type', 'duration_minutes', 'categories_count', 'players_count']
    
    def get_players_count(self, obj):
        return obj.player_records.count()


class TrainingSessionDetailSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source='team.name', read_only=True)
    coach_name = serializers.CharField(source='coach.user.get_full_name', read_only=True)
    categories = TrainingCategorySerializer(many=True, read_only=True)
    player_records = PlayerTrainingSerializer(many=True, read_only=True)
    
    class Meta:
        model = TrainingSession
        fields = ['id', 'session_id', 'title', 'description', 'date', 'start_time', 'end_time', 
                  'team', 'team_name', 'coach', 'coach_name', 'location',
                  'training_type', 'categories', 'notes', 'created_at', 'updated_at',
                  'duration_minutes', 'player_records']


class PlayerProgressSerializer(serializers.ModelSerializer):
    metrics_data = serializers.SerializerMethodField()
    player_name = serializers.CharField(source='user.get_full_name')
    team_name = serializers.CharField(source='team.name')
    
    class Meta:
        model = Player
        fields = ['user_id', 'player_name', 'team', 'team_name', 'metrics_data']
    
  
    def get_metrics_data(self, obj):
        # Get query parameters
        metric_id = self.context.get('request').query_params.get('metric_id', None)
        date_from = self.context.get('request').query_params.get('date_from', None)
        date_to = self.context.get('request').query_params.get('date_to', None)
        
        # Base queryset for player's metrics
        records_query = PlayerMetricRecord.objects.filter(
            player_training__player=obj
        ).select_related(
            'player_training__session',
            'metric'
        ).order_by(
            'player_training__session__date'
        )
        
        # Apply filters if provided
        if metric_id:
            records_query = records_query.filter(metric_id=metric_id)
        if date_from:
            records_query = records_query.filter(player_training__session__date__gte=date_from)
        if date_to:
            records_query = records_query.filter(player_training__session__date__lte=date_to)
        
        # Group by metric
        metrics_data = {}
        for record in records_query:
            metric_id = record.metric.id
            if metric_id not in metrics_data:
                metrics_data[metric_id] = {
                    'metric_id': metric_id,
                    'metric_name': record.metric.name,
                    'unit': record.metric.unit,
                    'is_lower_better': record.metric.is_lower_better,
                    'data_points': []
                }
                
            metrics_data[metric_id]['data_points'].append({
                'date': record.player_training.session.date,
                'value': record.value,
                'notes': record.notes,
                'improvement_from_last': record.improvement_from_last,
                'improvement_percentage': record.improvement_percentage
            })
        
        return list(metrics_data.values())


class TeamTrainingAnalyticsSerializer(serializers.ModelSerializer):
    attendance_rate = serializers.SerializerMethodField()
    training_sessions_count = serializers.SerializerMethodField()
    player_metrics_summary = serializers.SerializerMethodField()
    
    class Meta:
        model = Team
        fields = ['id', 'name', 'attendance_rate', 'training_sessions_count', 'player_metrics_summary']
    
    def get_attendance_rate(self, obj):
        # Get query parameters for date range
        date_from = self.context.get('request').query_params.get('date_from', None)
        date_to = self.context.get('request').query_params.get('date_to', None)
        
        # Query for team training sessions
        sessions_query = TrainingSession.objects.filter(team=obj)
        if date_from:
            sessions_query = sessions_query.filter(date__gte=date_from)
        if date_to:
            sessions_query = sessions_query.filter(date__lte=date_to)
            
        # Calculate attendance statistics
        total_attendance_records = PlayerTraining.objects.filter(session__in=sessions_query).count()
        if total_attendance_records == 0:
            return {
                'present_rate': 0,
                'absent_rate': 0,
                'late_rate': 0,
                'excused_rate': 0
            }
            
        present_count = PlayerTraining.objects.filter(
            session__in=sessions_query, attendance_status='present'
        ).count()
        absent_count = PlayerTraining.objects.filter(
            session__in=sessions_query, attendance_status='absent'
        ).count()
        late_count = PlayerTraining.objects.filter(
            session__in=sessions_query, attendance_status='late'
        ).count()
        excused_count = PlayerTraining.objects.filter(
            session__in=sessions_query, attendance_status='excused'
        ).count()
        
        return {
            'present_rate': round(present_count / total_attendance_records * 100, 2),
            'absent_rate': round(absent_count / total_attendance_records * 100, 2),
            'late_rate': round(late_count / total_attendance_records * 100, 2),
            'excused_rate': round(excused_count / total_attendance_records * 100, 2)
        }
    
    def get_training_sessions_count(self, obj):
        # Get query parameters for date range
        date_from = self.context.get('request').query_params.get('date_from', None)
        date_to = self.context.get('request').query_params.get('date_to', None)
        
        # Query for team training sessions
        sessions_query = TrainingSession.objects.filter(team=obj)
        if date_from:
            sessions_query = sessions_query.filter(date__gte=date_from)
        if date_to:
            sessions_query = sessions_query.filter(date__lte=date_to)
            
        return sessions_query.count()
    
    def get_player_metrics_summary(self, obj):
        # Get query parameters
        metric_id = self.context.get('request').query_params.get('metric_id', None)
        date_from = self.context.get('request').query_params.get('date_from', None)
        date_to = self.context.get('request').query_params.get('date_to', None)
        
        if not metric_id:
            return []
        
        # Get all players in the team
        players = obj.players.all()
        
        # For each player, get their metrics for the specified period
        players_data = []
        
        for player in players:
            records_query = PlayerMetricRecord.objects.filter(
                player_training__player=player,
                metric_id=metric_id
            ).select_related('player_training__session')
            
            if date_from:
                records_query = records_query.filter(player_training__session__date__gte=date_from)
            if date_to:
                records_query = records_query.filter(player_training__session__date__lte=date_to)
                
            if not records_query.exists():
                continue
            
            # Get first and last record in the period to calculate improvement
            first_record = records_query.order_by('player_training__session__date').first()
            last_record = records_query.order_by('-player_training__session__date').first()
            
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
                    'player_id': player.user_id,
                    'player_name': f"{player.user.first_name} {player.user.last_name}",
                    'first_value': first_record.value,
                    'last_value': last_record.value,
                    'improvement': improvement,
                    'improvement_percentage': percentage
                })
                
        return players_data
