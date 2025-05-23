from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Avg, Max, Min
from django.utils import timezone
import logging

from .models import (
    MetricUnit,
    TrainingCategory, 
    TrainingSession, 
    PlayerTraining, 
    TrainingMetric, 
    PlayerMetricRecord
)
from .filters import TrainingSessionFilter, PlayerTrainingFilter
from .serializers import (
    MetricUnitSerializer,
    TrainingCategorySerializer,
    TrainingSessionListSerializer,
    TrainingSessionDetailSerializer,
    PlayerTrainingSerializer,
    TrainingMetricSerializer,
    PlayerMetricRecordSerializer,
    PlayerProgressSerializer,
    TeamTrainingAnalyticsSerializer
)
from teams.models import Player, Team
from rest_framework.pagination import PageNumberPagination


class TrainingPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

class MetricUnitViewSet(viewsets.ModelViewSet):
    queryset = MetricUnit.objects.all().order_by('name')
    serializer_class = MetricUnitSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'code', 'description']

class TrainingCategoryViewSet(viewsets.ModelViewSet):
    queryset = TrainingCategory.objects.all()
    serializer_class = TrainingCategorySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'description']

class TrainingMetricViewSet(viewsets.ModelViewSet):
    queryset = TrainingMetric.objects.all()
    serializer_class = TrainingMetricSerializer
    permission_classes = [IsAuthenticated]    
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category', 'sessions']
    search_fields = ['name', 'description']

class TrainingSessionViewSet(viewsets.ModelViewSet):
    queryset = TrainingSession.objects.all().order_by('-date', '-start_time')
    permission_classes = [IsAuthenticated]
    pagination_class = TrainingPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = TrainingSessionFilter
    search_fields = ['title', 'description', 'location']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return TrainingSessionListSerializer
        return TrainingSessionDetailSerializer
        
    def list(self, request, *args, **kwargs):
        # Log the request parameters for debugging
        logger = logging.getLogger(__name__)
        logger.info(f"Training session list - Query params: {request.query_params}")
        
        return super().list(request, *args, **kwargs)
    
    @action(detail=True, methods=['post'])
    def add_players(self, request, pk=None):
        """Add multiple players to a training session"""
        session = self.get_object()
        player_ids = request.data.get('player_ids', [])
        attendance_status = request.data.get('attendance_status', 'present')

        # If no player_ids provided and session is a team session, add all team players
        if not player_ids and session.training_type == 'team' and session.team:
            player_ids = list(session.team.players.values_list('user_id', flat=True))

        if not player_ids:
            return Response(
                {"detail": "No player IDs provided and session is not a team session or team has no players."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get existing player trainings for this session
        existing_players = set(
            PlayerTraining.objects.filter(
                session=session
            ).values_list('player_id', flat=True)
        )

        # Add players not already in the session
        added_count = 0
        for player_id in player_ids:
            if player_id not in existing_players:
                try:
                    player = Player.objects.get(user_id=player_id)
                    PlayerTraining.objects.create(
                        player=player,
                        session=session,
                        attendance_status=attendance_status
                    )
                    added_count += 1
                except Player.DoesNotExist:
                    pass

        return Response({
            "detail": f"Added {added_count} players to training session",
            "added_count": added_count
        })
        
    @action(detail=True, methods=['get'])
    def analytics(self, request, pk=None):
        """Get analytics for a specific training session"""
        session = self.get_object()
        
        # Calculate attendance statistics
        attendance_stats = PlayerTraining.objects.filter(
            session=session
        ).values('attendance_status').annotate(count=Count('id'))
        
        # Format attendance data
        attendance_data = {
            'present': 0,
            'absent': 0,
            'late': 0,
            'excused': 0,
        }
        total_players = 0
        
        for stat in attendance_stats:
            status = stat['attendance_status']
            count = stat['count']
            attendance_data[status] = count
            total_players += count
        
        # Calculate percentages for attendance
        attendance_data_percentages = {}
        for status in attendance_data:
            if total_players > 0:
                attendance_data_percentages[f"{status}_percentage"] = round(
                    attendance_data[status] / total_players * 100, 2
                )
            else:
                attendance_data_percentages[f"{status}_percentage"] = 0
        # Merge percentages into a new dict to avoid changing dict size during iteration
        attendance_data_with_percentages = {**attendance_data, **attendance_data_percentages}
        
        # Get metrics recorded in this session
        metrics_summary = PlayerMetricRecord.objects.filter(
            player_training__session=session
        ).values('metric__name', 'metric__unit', 'metric__is_lower_better').annotate(
            avg_value=Avg('value'),
            min_value=Min('value'),
            max_value=Max('value'),
            records_count=Count('id')
        )
        
        return Response({
            'total_players': total_players,
            'attendance': attendance_data_with_percentages,
            'metrics_summary': metrics_summary
        })
    
    def perform_create(self, serializer):
        session = serializer.save()
        # Automatically add all team players if session is a team session
        if session.training_type == 'team' and session.team:
            player_ids = list(session.team.players.values_list('user_id', flat=True))
            existing_players = set(
                PlayerTraining.objects.filter(session=session).values_list('player_id', flat=True)
            )
            for player_id in player_ids:
                if player_id not in existing_players:
                    try:
                        player = Player.objects.get(user_id=player_id)
                        PlayerTraining.objects.create(
                            player=player,
                            session=session,
                        )
                    except Player.DoesNotExist:
                        pass

    @action(detail=True, methods=['post'])
    def assign_metrics(self, request, pk=None):
        """Assign specific metrics to a training session and create records for all players"""
        session = self.get_object()
        metric_ids = request.data.get('metrics', [])
        
        if not isinstance(metric_ids, list):
            return Response(
                {"detail": "Metrics must be provided as a list of IDs"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Get existing metrics to validate IDs
        valid_metrics = TrainingMetric.objects.filter(id__in=metric_ids)
        valid_metric_ids = set(valid_metrics.values_list('id', flat=True))
        
        # Create a list to track which metrics were not found
        invalid_metrics = [mid for mid in metric_ids if mid not in valid_metric_ids]
        
        # Many-to-many relationships can be set by assigning a list
        # This replaces any existing metrics with the new list
        session.metrics.set(valid_metric_ids)
        
        # Get all player trainings for this session
        player_trainings = PlayerTraining.objects.filter(session=session)
        
        # Create or update metric records for all players in the session
        created_records = []
        updated_records = []
        
        for player_training in player_trainings:
            # Assign metrics to player training
            player_training.assigned_metrics.set(valid_metric_ids)
            
            # Create placeholder records for each metric
            for metric in valid_metrics:
                record, created = PlayerMetricRecord.objects.get_or_create(
                    player_training=player_training,
                    metric=metric,
                    defaults={
                        'value': 0,  # Default placeholder value
                        'notes': 'Metric assigned - pending record'
                    }
                )
                if created:
                    created_records.append({
                        'player': player_training.player.user.get_full_name(),
                        'metric': metric.name
                    })
                else:
                    updated_records.append({
                        'player': player_training.player.user.get_full_name(),
                        'metric': metric.name
                    })
        
        return Response({
            "detail": f"Assigned {len(valid_metric_ids)} metrics to training session",
            "count": len(valid_metric_ids),
            "invalid_metrics": invalid_metrics if invalid_metrics else None,
            "created_records": created_records,
            "updated_records": updated_records
        })

class PlayerTrainingViewSet(viewsets.ModelViewSet):
    queryset = PlayerTraining.objects.all()
    serializer_class = PlayerTrainingSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_class = PlayerTrainingFilter
    
    @action(detail=True, methods=['post'])
    def record_metrics(self, request, pk=None):
        """Record multiple metrics for a player's training"""
        player_training = self.get_object()
        metrics_data = request.data.get('metrics', [])
        
        if not metrics_data:
            return Response(
                {"detail": "No metrics data provided"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        created_records = []
        
        for metric_data in metrics_data:
            metric_id = metric_data.get('metric_id')
            value = metric_data.get('value')
            notes = metric_data.get('notes', '')
            
            if not metric_id or value is None:
                continue
            
            try:
                metric = TrainingMetric.objects.get(id=metric_id)
                
                # Check if a record already exists for this metric
                record, created = PlayerMetricRecord.objects.update_or_create(
                    player_training=player_training,
                    metric=metric,
                    defaults={
                        'value': value,
                        'notes': notes,
                        'recorded_by_id': getattr(request.user, 'coach_profile_id', None)
                    }
                )
                
                created_records.append({
                    'id': record.id,
                    'metric': metric.name,
                    'value': record.value,
                    'created': created
                })
                
            except TrainingMetric.DoesNotExist:
                pass
        return Response({
            "detail": f"Recorded {len(created_records)} metrics",
            "records": created_records,
            "previous_records": self._get_previous_records(player_training)
        })
        
    @action(detail=True, methods=['post'])
    def assign_metrics(self, request, pk=None):
        """Assign specific metrics to a player's training record"""
        player_training = self.get_object()
        metric_ids = request.data.get('metrics', [])
        
        if not isinstance(metric_ids, list):
            return Response(
                {"detail": "Metrics must be provided as a list of IDs"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Get existing metrics to validate IDs
        valid_metrics = set(TrainingMetric.objects.filter(
            id__in=metric_ids
        ).values_list('id', flat=True))
        
        # Create a list to track which metrics were not found
        invalid_metrics = [mid for mid in metric_ids if mid not in valid_metrics]
        
        # Many-to-many relationships can be set by assigning a list
        # This replaces any existing metrics with the new list
        player_training.assigned_metrics.set(valid_metrics)
        
        return Response({
            "detail": f"Assigned {len(valid_metrics)} metrics to player training record",
            "count": len(valid_metrics),
            "invalid_metrics": invalid_metrics if invalid_metrics else None
        })
        
    def _get_previous_records(self, player_training):
        """Get previous records for this player across metrics"""
        player = player_training.player
        current_session = player_training.session
        
        # Find the most recent training session before this one
        previous_trainings = PlayerTraining.objects.filter(
            player=player,
            session__date__lt=current_session.date
        ).order_by('-session__date')
        
        if not previous_trainings.exists():
            return []
            
        previous_training = previous_trainings.first()
        
        # Get metric records from that session
        previous_records = PlayerMetricRecord.objects.filter(
            player_training=previous_training
        ).select_related('metric')
        
        return [
            {
                'metric_id': record.metric.id,
                'metric_name': record.metric.name,
                'value': record.value,
                'session_date': previous_training.session.date,
                'unit': record.metric.metric_unit.code if record.metric.metric_unit else '-'
            }
            for record in previous_records
        ]
    @action(detail=True, methods=['patch'])
    def update_attendance(self, request, pk=None):
        """Update attendance status for a player's training record"""
        player_training = self.get_object()
        new_status = request.data.get('attendance_status')
        notes = request.data.get('notes', player_training.notes)  # Use existing notes if not provided
        valid_statuses = ['present', 'absent', 'late', 'excused', 'pending']
        
        if new_status not in valid_statuses:
            return Response({"detail": "Invalid attendance status."}, status=status.HTTP_400_BAD_REQUEST)
            
        player_training.attendance_status = new_status        
        player_training.notes = notes
        player_training.save()
        
        return Response({
            "detail": "Attendance updated.",
            "attendance_status": new_status,
            "notes": notes
        })
        
    @action(detail=True, methods=['get'])
    def previous_records(self, request, pk=None):
        """Get previous metric records for this player"""
        player_training = self.get_object()
        previous_records = self._get_previous_records(player_training)
        
        return Response({
            "previous_records": previous_records
        })
        
    @action(detail=False, methods=['post'])
    def bulk_update_attendance(self, request):
        """Update attendance status for multiple player training records"""
        session_id = request.data.get('sessionId')
        player_records = request.data.get('playerRecords', [])
        valid_statuses = ['present', 'absent', 'late', 'excused', 'pending']
        
        if not session_id:
            return Response({"detail": "Session ID is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        if not player_records:
            return Response({"detail": "No player records provided."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Track updated records and any errors
        updated_count = 0
        errors = []
        
        for record in player_records:
            record_id = record.get('id')
            new_status = record.get('attendance_status')
            notes = record.get('notes', '')
            
            if not record_id or not new_status:
                continue
                
            if new_status not in valid_statuses:
                errors.append(f"Invalid status '{new_status}' for record {record_id}")
                continue
                
            try:
                player_training = PlayerTraining.objects.get(id=record_id)
                player_training.attendance_status = new_status
                player_training.notes = notes
                player_training.save()
                updated_count += 1
            except PlayerTraining.DoesNotExist:
                errors.append(f"Record {record_id} not found")
        
        return Response({
            "detail": f"Updated {updated_count} attendance records",
            "updated_count": updated_count,
            "errors": errors if errors else None
        })
        

class PlayerMetricRecordViewSet(viewsets.ModelViewSet):
    queryset = PlayerMetricRecord.objects.all().select_related(
        'player_training__player', 'player_training__session', 'metric'
    )
    serializer_class = PlayerMetricRecordSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['player_training__player', 'metric', 'player_training__session']

class PlayerProgressViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Player.objects.all()
    serializer_class = PlayerProgressSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['team']
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context
        
    def get_queryset(self):
        # Return all players, not just ones with training records
        # This prevents 404 errors when a player has no training data
        return super().get_queryset()      
    @action(detail=False, methods=['get'])
    def multi_player(self, request):
        """
        Fetch progress data for multiple players at once in a more efficient way.
        This optimized endpoint fetches all player data in a single database query
        for an entire team or selected players.
        
        Expects GET parameters:
        - team: team_slug (required if player_ids not provided)
        - metric_id: metric_id (required)
        - date_from: "YYYY-MM-DD" (optional)
        - date_to: "YYYY-MM-DD" (optional)
        - player_ids: comma-separated list of player IDs (optional, for filtering specific players within a team)
        - limit: int (optional, limit the number of data points per player, default is all)
        - latest_only: boolean (optional, only fetch most recent training session data, default false)
        - page_size: int (optional, pagination control, default 50)
        - page: int (optional, pagination control, default 1)
        - no_cache: boolean (optional, bypass cache, default false)
        """
        from django.db.models import Subquery, OuterRef, Prefetch, Max, F
        from django.db.models.functions import Lag
        from django.db.models.expressions import Window
        from django.core.cache import cache
        from trainings.utils import batch_fetch_record_data, calculate_player_improvement
        import time
        import hashlib
        import json
        
        # Start timing
        start_time = time.time()
          # Get query parameters
        team_slug = request.query_params.get('team')
        metric_id = request.query_params.get('metric_id')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        player_ids_param = request.query_params.get('player_ids', '')
        limit = request.query_params.get('limit')
        latest_only = request.query_params.get('latest_only', 'false').lower() == 'true'
        no_cache = request.query_params.get('no_cache', 'false').lower() == 'true'
        
        # Pagination parameters
        try:
            page_size = int(request.query_params.get('page_size', 50))
            page = int(request.query_params.get('page', 1))
        except ValueError:
            page_size = 50
            page = 1
            
        # Parse player_ids from comma-separated string if provided
        player_ids = []
        if player_ids_param:
            player_ids = [pid for pid in player_ids_param.split(',') if pid]
        
        if not metric_id:
            return Response({"detail": "Metric ID is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        # Validate required parameters
        if not team_slug and not player_ids:
            return Response(
                {"detail": "Either team slug or player IDs must be provided."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Try to get from cache if caching is enabled
        if not no_cache:
            # Create a unique cache key based on all request parameters
            cache_key_parts = [
                'player_progress_multi',
                team_slug or '',
                metric_id,
                date_from or '',
                date_to or '',
                player_ids_param or '',
                str(limit or ''),
                str(latest_only),
                str(page),
                str(page_size)
            ]
            cache_key = hashlib.md5(json.dumps(cache_key_parts).encode()).hexdigest()
            
            # Check if we have a cached response
            cached_response = cache.get(cache_key)
            if cached_response:
                # Add cache hit info to response metadata
                cached_response['performance']['cache_hit'] = True
                return Response(cached_response)        # Get metric information (we need this even if there are no records)
        try:
            # Handle "overall" metric specially
            if metric_id == 'overall':
                metric_data = {
                    'metric_id': 'overall',
                    'metric_name': 'Overall Performance',
                    'unit': '%',
                    'is_lower_better': False  # For overall, higher is always better
                }
            else:                # For regular metrics, fetch from database
                metric = TrainingMetric.objects.select_related('metric_unit').only('name', 'is_lower_better', 'metric_unit__code').get(id=metric_id)
                metric_data = {
                    'metric_id': int(metric_id),
                    'metric_name': metric.name,
                    'unit': metric.metric_unit.code if metric.metric_unit else '-',
                    'is_lower_better': metric.is_lower_better,
                }
        except TrainingMetric.DoesNotExist:
            return Response({"detail": "Metric not found."}, status=status.HTTP_404_NOT_FOUND)
            
        # Build player query with optimized select_related 
        if team_slug:
            players_query = Player.objects.filter(team__slug=team_slug)
            if player_ids:
                players_query = players_query.filter(user_id__in=player_ids)
        else:
            players_query = Player.objects.filter(user_id__in=player_ids)
            
        # Optimize player query to fetch only needed fields 
        players_query = players_query.select_related('team', 'user').only(
            'user_id', 'team_id', 'team__name', 'team__slug', 'user__first_name', 'user__last_name'
        )
        
        # Count total players for pagination metadata
        total_players = players_query.count()
        
        # Apply pagination to players query for large datasets
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_players = list(players_query[start_idx:end_idx])
        
        # If no players found after pagination
        if not paginated_players:
            return Response({"detail": "No players found with the provided criteria."}, status=status.HTTP_404_NOT_FOUND)
        
        # Get all user_ids from the paginated players to use in our records query
        selected_player_ids = [player.user_id for player in paginated_players]
        
        # Prepare response structure for all requested players
        player_info = {}
        for player in paginated_players:
            player_id = player.user_id
            player_info[player_id] = {
                'user_id': player_id,
                'player_name': player.user.get_full_name(),
                'team': player.team_id,
                'team_slug': player.team.slug if player.team else None,
                'team_name': player.team.name if player.team else None,
                'metrics_data': []
            }
        
        # Fetch player metric records using our optimized utility
        records_by_player = batch_fetch_record_data(
            selected_player_ids, 
            metric_id, 
            date_from, 
            date_to
        )
        
        # Apply limit if specified
        if limit and limit.isdigit():
            for player_id in records_by_player:
                # Sort by date to ensure we get most recent records
                records_by_player[player_id].sort(key=lambda x: x['date'])
                # Apply limit to keep only the most recent records
                records_by_player[player_id] = records_by_player[player_id][-limit_val:]
                
        # If latest_only is true, keep only the latest record for each player
        if latest_only:
            for player_id in records_by_player:
                if records_by_player[player_id]:
                    # Sort by date and keep only the most recent record
                    records_by_player[player_id].sort(key=lambda x: x['date'])
                    records_by_player[player_id] = [records_by_player[player_id][-1]]
          # Calculate overall improvement metrics for each player
        player_improvements = calculate_player_improvement(
            records_by_player, 
            metric_data['is_lower_better'],  # Use the is_lower_better from metric_data to handle 'overall' case
            metric_id  # Pass the metric_id to enable special handling for 'overall' metric
        )
        
        # Build the final response structure
        for player_id, records in records_by_player.items():
            if player_id in player_info:
                # Create metric data structure for this player
                player_metric_data = dict(metric_data)
                
                # Attach the data points (records)
                player_metric_data['data_points'] = records
                
                # Add to player's metrics
                player_info[player_id]['metrics_data'] = [player_metric_data]
                
                # Add improvement metrics if available
                if player_id in player_improvements:
                    improvement_data = player_improvements[player_id]
                    
                    player_info[player_id].update({
                        'overall_improvement': improvement_data['overall_improvement'],
                        'recent_improvement': improvement_data['recent_improvement'],
                        'best_performance': improvement_data['best_performance'],
                        'training_count': len(records)
                    })
        
        # Format response with pagination and performance metadata
        response_data = {
            'results': player_info,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total_players': total_players,
                'total_pages': (total_players + page_size - 1) // page_size
            },
            'performance': {
                'execution_time_ms': round((time.time() - start_time) * 1000, 2),
                'cache_hit': False,
                'metrics_evaluated': len(selected_player_ids),
                'data_points_count': sum(len(records) for records in records_by_player.values())
            }
        }
        
        # Cache the response if caching is enabled
        if not no_cache:
            # Create a unique cache key as we did before
            cache_key_parts = [
                'player_progress_multi',
                team_slug or '',
                metric_id,
                date_from or '',
                date_to or '',
                player_ids_param or '',
                str(limit or ''),
                str(latest_only),
                str(page),
                str(page_size)
            ]
            cache_key = hashlib.md5(json.dumps(cache_key_parts).encode()).hexdigest()
            
            # Cache for 5 minutes (300 seconds) - adjust as needed
            cache.set(cache_key, response_data, 300)
        
        return Response(response_data)
        

class TeamTrainingAnalyticsViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Team.objects.all()
    serializer_class = TeamTrainingAnalyticsSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['sport']
    search_fields = ['name']
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context
