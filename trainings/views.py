from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from sports_management.permissions import IsAdminUser, IsCoachUser, IsAdminOrCoachUser
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Avg, Max, Min
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.core.exceptions import PermissionDenied
import logging
import time

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
)
from teams.models import Player, Team
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, F
from django.utils.dateparse import parse_date


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
    
    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        - GET requests are accessible to authenticated users
        - POST/PUT/PATCH/DELETE requests are restricted to admin and coach users
        """
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            permission_classes = [IsAdminOrCoachUser]
        else:
            permission_classes = [IsAuthenticated]
            
        return [permission() for permission in permission_classes]
    
    def perform_create(self, serializer):
        """Set creation logic based on user role"""
        user = self.request.user
        
        # Admin-created units are automatically system defaults
        if user.is_admin:
            serializer.save(created_by=user, is_default=True)
        # Coach-created units are not system defaults
        else:
            serializer.save(created_by=user, is_default=False)
    
    def perform_update(self, serializer):
        """Allow updates based on user role and ownership"""
        user = self.request.user
        instance = serializer.instance
        
        # Admin can update any unit
        if user.is_admin:
            serializer.save()
        # Coach can only update units they created (non-default)
        elif user.is_coach:
            if instance.is_default:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("Coaches cannot edit system default units")
            if instance.created_by != user:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("You can only edit units you created")
            serializer.save()
        else:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You don't have permission to update metric units")
    
    def perform_destroy(self, instance):
        """Allow deletion based on user role and ownership"""
        user = self.request.user
        
        # Admin can delete any unit (including system defaults)
        if user.is_admin:
            instance.delete()
        # Coach can only delete units they created (non-default)
        elif user.is_coach:
            if instance.is_default:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("Coaches cannot delete system default units")
            if instance.created_by != user:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("You can only delete units you created")
            instance.delete()
        else:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You don't have permission to delete metric units")

class TrainingCategoryViewSet(viewsets.ModelViewSet):
    queryset = TrainingCategory.objects.all()
    serializer_class = TrainingCategorySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'description']
    
    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        - GET requests are accessible to authenticated users
        - POST/PUT/PATCH/DELETE requests are restricted to admin users only
        """
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            permission_classes = [IsAdminUser]
        else:
            permission_classes = [IsAuthenticated]
            
        return [permission() for permission in permission_classes]

class TrainingMetricViewSet(viewsets.ModelViewSet):
    queryset = TrainingMetric.objects.all()
    serializer_class = TrainingMetricSerializer
    permission_classes = [IsAuthenticated]    
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category', 'sessions']
    search_fields = ['name', 'description']
    
    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        - GET requests are accessible to authenticated users
        - POST/PUT/PATCH/DELETE requests are restricted to admin users only
        """
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            permission_classes = [IsAdminUser]
        else:
            permission_classes = [IsAuthenticated]
            
        return [permission() for permission in permission_classes]

class TrainingSessionViewSet(viewsets.ModelViewSet):
    queryset = TrainingSession.objects.all().order_by('-date', '-start_time')
    permission_classes = [IsAuthenticated]
    pagination_class = TrainingPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = TrainingSessionFilter
    search_fields = ['title', 'description', 'location']
    
    def get_queryset(self):
        """
        Return training sessions based on user role:
        - Admin: All training sessions
        - Coach: Only their team's training sessions
        - Player: Only their team's training sessions
        - Others: Permission denied for all actions including list
        """
        user = self.request.user
        
        # Base queryset
        base_queryset = TrainingSession.objects.all().order_by('-date', '-start_time')
        
        # For admins, show all training sessions
        if user.is_admin:
            return base_queryset
            
        # For coaches, show only their team's training sessions
        if hasattr(user, 'coach_profile'):
            coach_teams = user.coach_profile.teams.all()
            return base_queryset.filter(team__in=coach_teams)
            
        # For players, show only their team's training sessions
        if hasattr(user, 'player_profile') and user.player_profile.team:
            player_team = user.player_profile.team
            return base_queryset.filter(team=player_team)
            
        # User doesn't have appropriate role - deny access
        raise PermissionDenied("You don't have permission to access training session data")
    
    def get_object(self):
        """
        Ensures training sessions can only be accessed based on user role permissions
        """
        # Store the unfiltered queryset
        unfiltered_queryset = TrainingSession.objects.all()
        
        # Get the filtered queryset based on user role
        filtered_queryset = self.filter_queryset(self.get_queryset())

        # Get the lookup value from the URL
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs[lookup_url_kwarg]

        # Try to determine if the lookup value is a numeric ID
        try:
            is_numeric = lookup_value.isdigit()
        except (AttributeError, ValueError):
            is_numeric = False

        if is_numeric:
            # If it's numeric, look up by ID
            filter_kwargs = {"pk": lookup_value}
        else:
            # Otherwise, use default lookup field
            filter_kwargs = {self.lookup_field: lookup_value}

        # First check if the object exists at all in the unfiltered queryset
        try:
            obj = unfiltered_queryset.get(**filter_kwargs)
        except TrainingSession.DoesNotExist:
            # If the training session doesn't exist at all, raise 404
            from django.http import Http404
            raise Http404("Training session does not exist")
        
        # Now check if the object is in the filtered queryset (user has access)
        if not filtered_queryset.filter(**filter_kwargs).exists():
            # If the training session exists but user doesn't have access, raise permission denied
            raise PermissionDenied("You don't have permission to access this training session")
        
        # Get the object from the filtered queryset
        obj = filtered_queryset.get(**filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj
    
    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        - GET requests are accessible to authenticated users (filtered by get_queryset)
        - POST/CREATE requests are restricted to admin or coach users
        - PUT/PATCH/DELETE requests can be done by admins or coaches (with team restrictions)
        """
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            permission_classes = [IsAdminOrCoachUser]
        else:
            permission_classes = [IsAuthenticated]
            
        return [permission() for permission in permission_classes]
    
    def get_serializer_class(self):
        if self.action == 'list':
            return TrainingSessionListSerializer
        return TrainingSessionDetailSerializer
        
    def list(self, request, *args, **kwargs):
        # Log the request parameters for debugging
        logger = logging.getLogger(__name__)
        logger.info(f"Training session list - Query params: {request.query_params}")
        
        return super().list(request, *args, **kwargs)
    
    def perform_create(self, serializer):
        from .services import TrainingSessionService
        
        # For coaches, ensure they can only create sessions for their teams
        if self.request.user.is_coach and hasattr(self.request.user, 'coach_profile'):
            team = serializer.validated_data.get('team')
            if team:
                coach_teams = list(self.request.user.coach_profile.teams.all())
                if team not in coach_teams:
                    raise PermissionDenied("You can only create training sessions for your own teams")
        
        session = serializer.save()
        # Automatically add all team players if session is a team session
        if session.training_type == 'team' and session.team:
            service = TrainingSessionService()
            service.auto_add_team_players(session)
    
    def perform_update(self, serializer):
        """Only allow coaches to update training sessions for their own teams"""
        if self.request.user.is_admin:
            # Admins can update any training session
            serializer.save()
        elif self.request.user.is_coach and hasattr(self.request.user, 'coach_profile'):
            # Coaches can only update training sessions for their teams
            coach_teams = list(self.request.user.coach_profile.teams.all())
            session = serializer.instance
            
            # Check if the session belongs to one of the coach's teams
            if session.team and session.team in coach_teams:
                # Also check if they're trying to change the team to one they don't coach
                new_team = serializer.validated_data.get('team', session.team)
                if new_team not in coach_teams:
                    raise PermissionDenied("You can only assign training sessions to your own teams")
                serializer.save()
            else:
                raise PermissionDenied("You can only update training sessions for your own teams")
        else:
            raise PermissionDenied("You don't have permission to update training sessions")
    
    def perform_destroy(self, instance):
        """Only allow coaches to delete training sessions for their own teams"""
        if self.request.user.is_admin:
            # Admins can delete any training session
            instance.delete()
        elif self.request.user.is_coach and hasattr(self.request.user, 'coach_profile'):
            # Coaches can only delete training sessions for their teams
            coach_teams = list(self.request.user.coach_profile.teams.all())
            
            # Check if the session belongs to one of the coach's teams
            if instance.team and instance.team in coach_teams:
                instance.delete()
            else:
                raise PermissionDenied("You can only delete training sessions for your own teams")
        else:
            raise PermissionDenied("You don't have permission to delete training sessions")
    
    @action(detail=True, methods=['post'])
    def add_players(self, request, pk=None):
        """Add multiple players to a training session"""
        from .services import TrainingSessionService
        
        session = self.get_object()
        player_ids = request.data.get('player_ids', [])
        attendance_status = request.data.get('attendance_status', 'present')
        
        service = TrainingSessionService()
        result = service.add_players_to_session(session, player_ids, attendance_status)
        
        return Response({
            "detail": f"Added {result['added_count']} players to training session",
            "added_count": result['added_count']
        })
        
    @action(detail=True, methods=['get'])
    def analytics(self, request, pk=None):
        """Get analytics for a specific training session"""
        from .services import TrainingSessionService
        session = self.get_object()
        service = TrainingSessionService()
        analytics_data = service.get_session_analytics(session)
        
        return Response(analytics_data)
    def perform_create(self, serializer):
        from .services import TrainingSessionService
        
        session = serializer.save()
        # Automatically add all team players if session is a team session
        if session.training_type == 'team' and session.team:
            service = TrainingSessionService()
            service.auto_add_team_players(session)
    
    @action(detail=True, methods=['post'])
    def assign_metrics(self, request, pk=None):
        """Assign specific metrics to a training session and create records for all players"""
        from .services import TrainingSessionService
        
        session = self.get_object()
        metric_ids = request.data.get('metrics', [])
        
        if not isinstance(metric_ids, list):
            return Response(
                {"detail": "Metrics must be provided as a list of IDs"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        service = TrainingSessionService()
        result = service.assign_metrics_to_session(session, metric_ids)
        return Response({
            "detail": f"Assigned {result['assigned_count']} metrics to training session",
            "count": result['assigned_count'],
            "invalid_metrics": result.get('invalid_metrics'),
            "created_records": result.get('total_created_records', 0),
            "updated_records": result.get('total_deleted_records', 0),
            "player_results": result.get('player_results', [])
        })

class PlayerTrainingViewSet(viewsets.ModelViewSet):
    queryset = PlayerTraining.objects.all()
    serializer_class = PlayerTrainingSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_class = PlayerTrainingFilter
    
    def get_queryset(self):
        """
        Return player training records based on user role:
        - Admin: All player training records
        - Coach: Only player training records for their team's players
        - Player: Only their own training records
        - Others: Permission denied for all actions including list
        """
        user = self.request.user
        
        # Base queryset
        base_queryset = PlayerTraining.objects.all()
        
        # For admins, show all player training records
        if user.is_admin:
            return base_queryset
            
        # For coaches, show only player training records for their team's players
        if hasattr(user, 'coach_profile'):
            coach_teams = user.coach_profile.teams.all()
            return base_queryset.filter(session__team__in=coach_teams)
            
        # For players, show only their own training records
        if hasattr(user, 'player_profile'):
            return base_queryset.filter(player=user.player_profile)
            
        # User doesn't have appropriate role - deny access
        raise PermissionDenied("You don't have permission to access player training data")
    
    def get_object(self):
        """
        Ensures player training records can only be accessed based on user role permissions
        """
        # Store the unfiltered queryset
        unfiltered_queryset = PlayerTraining.objects.all()
        
        # Get the filtered queryset based on user role
        filtered_queryset = self.filter_queryset(self.get_queryset())

        # Get the lookup value from the URL
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs[lookup_url_kwarg]

        # Try to determine if the lookup value is a numeric ID
        try:
            is_numeric = lookup_value.isdigit()
        except (AttributeError, ValueError):
            is_numeric = False

        if is_numeric:
            # If it's numeric, look up by ID
            filter_kwargs = {"pk": lookup_value}
        else:
            # Otherwise, use default lookup field
            filter_kwargs = {self.lookup_field: lookup_value}

        # First check if the object exists at all in the unfiltered queryset
        try:
            obj = unfiltered_queryset.get(**filter_kwargs)
        except PlayerTraining.DoesNotExist:
            # If the player training record doesn't exist at all, raise 404
            from django.http import Http404
            raise Http404("Player training record does not exist")
        
        # Now check if the object is in the filtered queryset (user has access)
        if not filtered_queryset.filter(**filter_kwargs).exists():
            # If the player training record exists but user doesn't have access, raise permission denied
            raise PermissionDenied("You don't have permission to access this player training record")
        
        # Get the object from the filtered queryset
        obj = filtered_queryset.get(**filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj
    
    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        - GET requests are accessible to authenticated users (filtered by get_queryset)
        - POST/CREATE requests are restricted to admin or coach users
        - PUT/PATCH/DELETE requests can be done by admins or coaches (with team restrictions)
        """
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            permission_classes = [IsAdminOrCoachUser]
        else:
            permission_classes = [IsAuthenticated]
            
        return [permission() for permission in permission_classes]
    
    def perform_update(self, serializer):
        """Only allow coaches to update player training records for their own team's players"""
        if self.request.user.is_admin:
            # Admins can update any player training record
            serializer.save()
        elif self.request.user.is_coach and hasattr(self.request.user, 'coach_profile'):
            # Coaches can only update player training records for their team's players
            coach_teams = list(self.request.user.coach_profile.teams.all())
            player_training = serializer.instance
            
            # Check if the player training record belongs to one of the coach's teams
            if player_training.session.team and player_training.session.team in coach_teams:
                serializer.save()
            else:
                raise PermissionDenied("You can only update player training records for your own team's players")
        else:
            raise PermissionDenied("You don't have permission to update player training records")
    
    def perform_destroy(self, instance):
        """Only allow coaches to delete player training records for their own team's players"""
        if self.request.user.is_admin:
            # Admins can delete any player training record
            instance.delete()
        elif self.request.user.is_coach and hasattr(self.request.user, 'coach_profile'):
            # Coaches can only delete player training records for their team's players
            coach_teams = list(self.request.user.coach_profile.teams.all())
            
            # Check if the player training record belongs to one of the coach's teams
            if instance.session.team and instance.session.team in coach_teams:
                instance.delete()
            else:
                raise PermissionDenied("You can only delete player training records for your own team's players")
        else:
            raise PermissionDenied("You don't have permission to delete player training records")
    
    @action(detail=True, methods=['post'])
    def record_metrics(self, request, pk=None):
        """Record multiple metrics for a player's training"""
        from .services import PlayerTrainingService
        
        player_training = self.get_object()
        metrics_data = request.data.get('metrics', [])
        
        if not metrics_data:
            return Response(
                {"detail": "No metrics data provided"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        service = PlayerTrainingService()
        result = service.record_multiple_metrics(player_training, metrics_data, request.user)
        
        return Response({
            "detail": f"Recorded {len(result['records'])} metrics",
            "records": result['records'],
            "previous_records": result.get('previous_records', [])
        })
        
    @action(detail=True, methods=['post'])
    def assign_metrics(self, request, pk=None):
        """Assign specific metrics to a player's training record"""
        from .services import PlayerTrainingService
        
        player_training = self.get_object()
        metric_ids = request.data.get('metrics', [])
        
        if not isinstance(metric_ids, list):
            return Response(
                {"detail": "Metrics must be provided as a list of IDs"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        service = PlayerTrainingService()
        result = service.assign_metrics_to_player_training(player_training, metric_ids)
        
        return Response({
            "detail": f"Assigned {result['count']} metrics to player training record",
            "count": result['count'],
            "invalid_metrics": result.get('invalid_metrics')
        })
        
    def _get_previous_records(self, player_training):
        """Get previous records for this player across metrics"""
        from .services import PlayerTrainingService
        
        service = PlayerTrainingService()
        return service.get_previous_records(player_training)
    
    @action(detail=True, methods=['patch'])
    def update_attendance(self, request, pk=None):
        """Update attendance status for a player's training record"""
        from .services import PlayerTrainingService
        
        player_training = self.get_object()
        new_status = request.data.get('attendance_status')
        notes = request.data.get('notes', player_training.notes)
        
        service = PlayerTrainingService()
        result = service.update_attendance(player_training, new_status, notes)
        
        return Response({
            "detail": "Attendance updated.",
            "attendance_status": result['attendance_status'],
            "notes": result['notes']
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
        from .services import PlayerTrainingService
        
        session_id = request.data.get('sessionId')
        player_records = request.data.get('playerRecords', [])
        
        if not session_id:
            return Response({"detail": "Session ID is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not player_records:
            return Response({"detail": "No player records provided."}, status=status.HTTP_400_BAD_REQUEST)
        
        service = PlayerTrainingService()
        result = service.bulk_update_attendance(session_id, player_records)
        
        return Response({
            "detail": f"Updated {result['updated_count']} attendance records",
            "updated_count": result['updated_count'],
            "errors": result.get('errors')
        })
        

class PlayerMetricRecordViewSet(viewsets.ModelViewSet):
    queryset = PlayerMetricRecord.objects.all().select_related(
        'player_training__player', 'player_training__session', 'metric'
    )
    serializer_class = PlayerMetricRecordSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['player_training__player', 'metric', 'player_training__session']
    
    def get_queryset(self):
        """
        Return player metric records based on user role:
        - Admin: All player metric records
        - Coach: Only metric records for their team's players
        - Player: Only their own metric records
        - Others: Permission denied for all actions including list
        """
        user = self.request.user
        
        # Base queryset
        base_queryset = PlayerMetricRecord.objects.all().select_related(
            'player_training__player', 'player_training__session', 'metric'
        )
        
        # For admins, show all player metric records
        if user.is_admin:
            return base_queryset
            
        # For coaches, show only metric records for their team's players
        if hasattr(user, 'coach_profile'):
            coach_teams = user.coach_profile.teams.all()
            return base_queryset.filter(player_training__session__team__in=coach_teams)
            
        # For players, show only their own metric records
        if hasattr(user, 'player_profile'):
            return base_queryset.filter(player_training__player=user.player_profile)
            
        # User doesn't have appropriate role - deny access
        raise PermissionDenied("You don't have permission to access player metric records")
    
    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        - GET requests are accessible to authenticated users (filtered by get_queryset)
        - POST/CREATE requests are restricted to admin or coach users
        - PUT/PATCH/DELETE requests can be done by admins or coaches (with team restrictions)
        """
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            permission_classes = [IsAdminOrCoachUser]
        else:
            permission_classes = [IsAuthenticated]
            
        return [permission() for permission in permission_classes]
    
    def perform_update(self, serializer):
        """Only allow coaches to update metric records for their own team's players"""
        if self.request.user.is_admin:
            # Admins can update any metric record
            serializer.save()
        elif self.request.user.is_coach and hasattr(self.request.user, 'coach_profile'):
            # Coaches can only update metric records for their team's players
            coach_teams = list(self.request.user.coach_profile.teams.all())
            metric_record = serializer.instance
            
            # Check if the metric record belongs to one of the coach's teams
            if metric_record.player_training.session.team and metric_record.player_training.session.team in coach_teams:
                serializer.save()
            else:
                raise PermissionDenied("You can only update metric records for your own team's players")
        else:
            raise PermissionDenied("You don't have permission to update metric records")
    
    def perform_destroy(self, instance):
        """Only allow coaches to delete metric records for their own team's players"""
        if self.request.user.is_admin:
            # Admins can delete any metric record
            instance.delete()
        elif self.request.user.is_coach and hasattr(self.request.user, 'coach_profile'):
            # Coaches can only delete metric records for their team's players
            coach_teams = list(self.request.user.coach_profile.teams.all())
            
            # Check if the metric record belongs to one of the coach's teams
            if instance.player_training.session.team and instance.player_training.session.team in coach_teams:
                instance.delete()
            else:
                raise PermissionDenied("You can only delete metric records for your own team's players")
        else:
            raise PermissionDenied("You don't have permission to delete metric records")

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
        """
        Return player progress data based on user role:
        - Admin: All players
        - Coach: Only players from their teams
        - Player: Only their own data
        - Others: Permission denied for all actions including list
        """
        user = self.request.user
        
        # Base queryset
        base_queryset = Player.objects.all()
        
        # For admins, show all players
        if user.is_admin:
            return base_queryset
            
        # For coaches, show only players from their teams
        if hasattr(user, 'coach_profile'):
            coach_teams = user.coach_profile.teams.all()
            return base_queryset.filter(team__in=coach_teams)
            
        # For players, show only their own data
        if hasattr(user, 'player_profile'):
            return base_queryset.filter(id=user.player_profile.id)
            
        # User doesn't have appropriate role - deny access
        raise PermissionDenied("You don't have permission to access player progress data")
        
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
        """
        from .services import MultiPlayerProgressService
        try:
            service = MultiPlayerProgressService(request)
            response_data = service.get_multi_player_progress()
            return Response(response_data)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

class AttendanceAnalyticsViewSet(viewsets.ViewSet):
    """
    ViewSet for attendance analytics and reporting with role-based access control
    """
    permission_classes = [IsAuthenticated]
    
    def get_base_queryset(self, request):
        """
        Get base queryset for attendance data based on user role:
        - Admin: All attendance records
        - Coach: Only records for their team's players
        - Player: Only their own attendance records
        - Others: Permission denied
        """
        user = request.user
        
        # Base queryset
        base_queryset = PlayerTraining.objects.all()
        
        # For admins, show all attendance records
        if user.is_admin:
            return base_queryset
            
        # For coaches, show only records for their team's players
        if hasattr(user, 'coach_profile'):
            coach_teams = user.coach_profile.teams.all()
            return base_queryset.filter(session__team__in=coach_teams)
            
        # For players, show only their own attendance records
        if hasattr(user, 'player_profile'):
            return base_queryset.filter(player=user.player_profile)
            
        # User doesn't have appropriate role - deny access
        raise PermissionDenied("You don't have permission to access attendance analytics")
    
    @action(detail=False, methods=['get'])
    def overview(self, request):
        """Get attendance overview analytics"""
        try:
            # Apply role-based filtering first
            base_queryset = self.get_base_queryset(request)
            filters = self._get_filters(request)
            
            # Get attendance data with role-based filtering
            attendance_qs = base_queryset.filter(**filters)
            
            # Calculate overall stats
            total_records = attendance_qs.count()
            if total_records == 0:
                return Response({
                    'total_sessions': 0,
                    'total_attendees': 0,
                    'overall_attendance_rate': 0.0,
                    'average_attendance_per_session': 0.0,
                    'attendance_distribution': {},
                    'top_attendance': []
                })
            
            # Attendance distribution
            distribution = attendance_qs.values('attendance_status').annotate(
                count=Count('id')
            )
            
            attendance_distribution = {}
            for item in distribution:
                status = item['attendance_status'] or 'pending'
                attendance_distribution[status] = item['count']
            
            # Calculate rates
            present_count = attendance_distribution.get('present', 0)
            overall_rate = (present_count / total_records * 100) if total_records > 0 else 0
              # Session stats
            total_sessions = attendance_qs.values('session').distinct().count()
            avg_per_session = total_records / total_sessions if total_sessions > 0 else 0
              # Top performers (simplified)
            top_attendance = []
            
            data = {
                'total_sessions': total_sessions,
                'total_attendees': total_records,
                'overall_attendance_rate': round(overall_rate, 2),
                'average_attendance_per_session': round(avg_per_session, 2),
                'attendance_distribution': attendance_distribution,
                'top_attendance': top_attendance
            }
            
            return Response(data)
            
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def trends(self, request):
        """Get attendance trends over time"""
        try:
            # Apply role-based filtering first
            base_queryset = self.get_base_queryset(request)
            filters = self._get_filters(request)
            period = request.query_params.get('period', 'daily')
            
            # Get attendance data grouped by date with role-based filtering
            attendance_qs = base_queryset.filter(**filters).select_related(
                'session'
            )
            
            # Group by training session date
            trends_data = []
            session_dates = attendance_qs.values_list(
                'session__date', flat=True
            ).distinct().order_by('session__date')
            
            for date in session_dates:
                day_records = attendance_qs.filter(session__date=date)
                total = day_records.count()
                present = day_records.filter(attendance_status='present').count()
                
                attendance_rate = (present / total * 100) if total > 0 else 0
                
                trends_data.append({
                    'date': date.isoformat(),
                    'attendance_rate': round(attendance_rate, 2),
                    'total_attendees': total,
                    'present_count': present
                })
            return Response(trends_data)
            
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def heatmap(self, request):
        """Get attendance heatmap data"""        
        try:
            # Apply role-based filtering first
            base_queryset = self.get_base_queryset(request)
            filters = self._get_filters(request)
            
            # Get attendance data grouped by date with role-based filtering
            attendance_qs = base_queryset.filter(**filters).select_related(
                'session'
            )
            
            # Group by training session date
            heatmap_data = []
            session_dates = attendance_qs.values_list(
                'session__date', flat=True
            ).distinct().order_by('session__date')
            
            for date in session_dates:
                day_records = attendance_qs.filter(session__date=date)
                total = day_records.count()
                present = day_records.filter(attendance_status='present').count()
                
                attendance_rate = (present / total * 100) if total > 0 else 0
                
                heatmap_data.append({
                    'date': date.isoformat(),
                    'total_players': total,
                    'present_count': present,
                    'attendance_rate': round(attendance_rate, 2)
                })
            return Response(heatmap_data)
            
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def players(self, request):
        """Get individual player attendance analytics"""
        try:
            # Apply role-based filtering first
            base_queryset = self.get_base_queryset(request)
            filters = self._get_filters(request)
              # Get all player training records with role-based filtering
            attendance_qs = base_queryset.filter(**filters).select_related(
                'player__user', 'session'
            )
            
            # Group by player
            player_stats = {}
            for record in attendance_qs:
                player_id = record.player.user_id
                if player_id not in player_stats:
                    player_stats[player_id] = {
                        'player_id': player_id,
                        'player_name': record.player.user.get_full_name(),
                        'total_sessions': 0,
                        'present_count': 0,
                        'absent_count': 0,
                        'late_count': 0,
                        'excused_count': 0,
                        'current_streak': 0,
                        'best_streak': 0
                    }
                
                stats = player_stats[player_id]
                stats['total_sessions'] += 1
                
                if record.attendance_status == 'present':
                    stats['present_count'] += 1
                elif record.attendance_status == 'absent':
                    stats['absent_count'] += 1
                elif record.attendance_status == 'late':
                    stats['late_count'] += 1
                elif record.attendance_status == 'excused':
                    stats['excused_count'] += 1
            
            # Calculate attendance rates
            players_data = []
            for stats in player_stats.values():
                total = stats['total_sessions']
                present = stats['present_count']
                attendance_rate = (present / total * 100) if total > 0 else 0
                
                stats['attendance_rate'] = round(attendance_rate, 2)
                players_data.append(stats)
              # Sort by attendance rate
            players_data.sort(key=lambda x: x['attendance_rate'], reverse=True)
            return Response(players_data)
            
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def player_detail(self, request):
        """Get detailed attendance analytics for a specific player"""
        try:
            player_id = request.query_params.get('player_id')
            if not player_id:
                return Response(
                    {'error': 'player_id parameter is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Apply role-based filtering first
            base_queryset = self.get_base_queryset(request)
            filters = self._get_filters(request)
            filters['player__user_id'] = player_id
            
            # Get all player training records with role-based filtering
            attendance_qs = base_queryset.filter(**filters).select_related(
                'player__user', 'session'
            ).order_by('session__date')
            
            # Check if user has permission to view this specific player's data
            user = request.user
            if not user.is_admin and hasattr(user, 'player_profile'):
                # Players can only view their own data
                if str(user.player_profile.user_id) != str(player_id):
                    raise PermissionDenied("You can only view your own attendance data")
            elif not user.is_admin and hasattr(user, 'coach_profile'):
                # Coaches can only view data for players in their teams
                coach_teams = user.coach_profile.teams.all()
                player_accessible = attendance_qs.filter(session__team__in=coach_teams).exists()
                if not player_accessible:
                    raise PermissionDenied("You can only view attendance data for players in your teams")
            
            if not attendance_qs.exists():
                return Response({
                    'player_id': player_id,
                    'player_name': 'Unknown Player',
                    'total_sessions': 0,
                    'attendance_rate': 0.0,
                    'attendance_distribution': {},
                    'trends': [],
                    'recent_sessions': []
                })
            
            # Get player info from first record
            first_record = attendance_qs.first()
            player_name = first_record.player.user.get_full_name()
            
            # Calculate overall stats
            total_sessions = attendance_qs.count()
            present_count = attendance_qs.filter(attendance_status='present').count()
            absent_count = attendance_qs.filter(attendance_status='absent').count()
            late_count = attendance_qs.filter(attendance_status='late').count()
            excused_count = attendance_qs.filter(attendance_status='excused').count()
            
            attendance_rate = (present_count / total_sessions * 100) if total_sessions > 0 else 0
            
            # Attendance distribution
            attendance_distribution = {
                'present': present_count,
                'absent': absent_count,
                'late': late_count,
                'excused': excused_count
            }
            
            # Trends data (last 30 sessions or all if less)
            recent_records = attendance_qs.order_by('-session__date')[:30]
            trends = []
            for record in reversed(recent_records):
                trends.append({
                    'date': record.session.date.isoformat(),
                    'status': record.attendance_status or 'pending',
                    'session_name': record.session.title
                })
            
            # Recent sessions details
            recent_sessions = []
            for record in attendance_qs.order_by('-session__date')[:10]:
                recent_sessions.append({
                    'date': record.session.date.isoformat(),
                    'session_name': record.session.title,
                    'status': record.attendance_status or 'pending',
                    'notes': record.notes or ''
                })
            
            data = {
                'player_id': player_id,
                'player_name': player_name,
                'total_sessions': total_sessions,
                'present_count': present_count,
                'absent_count': absent_count,
                'late_count': late_count,
                'excused_count': excused_count,
                'attendance_rate': round(attendance_rate, 2),
                'attendance_distribution': attendance_distribution,
                'trends': trends,
                'recent_sessions': recent_sessions
            }
            
            return Response(data)
            
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    def _get_filters(self, request):
        """
        Extract filters from request parameters
        Note: Role-based filtering is handled separately in get_base_queryset()
        """
        filters = {}
        user = request.user
        
        # Team filter - apply additional restrictions based on role
        team_id = request.query_params.get('team_id')
        if team_id and team_id != 'all':
            # Validate team access based on user role
            if hasattr(user, 'coach_profile'):
                # Coaches can only filter by their own teams
                coach_teams = user.coach_profile.teams.all()
                if coach_teams.filter(id=team_id).exists():
                    filters['session__team_id'] = team_id
                else:
                    # Silently ignore unauthorized team filter for coaches
                    pass
            elif user.is_admin:
                # Admins can filter by any team
                filters['session__team_id'] = team_id
            # Players don't get team filtering as they only see their own data
        
        # Date range filters
        start_date = request.query_params.get('start_date')
        if start_date:
            try:
                start_date = parse_date(start_date)
                if start_date:
                    filters['session__date__gte'] = start_date
            except:
                pass
        
        end_date = request.query_params.get('end_date')
        if end_date:
            try:
                end_date = parse_date(end_date)
                if end_date:
                    filters['session__date__lte'] = end_date
            except:
                pass
        
        # Attendance status filter
        status_filter = request.query_params.get('status')
        if status_filter and status_filter != 'all':
            filters['attendance_status'] = status_filter
        
        return filters
