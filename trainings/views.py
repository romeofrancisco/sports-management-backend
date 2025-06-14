from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError
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
from .services.attendance_analytics_service import AttendanceAnalyticsService, TeamAnalyticsService, TrainingEfficiencyService
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
from .services.attendance_analytics_service import (
    AttendanceAnalyticsService,
    TeamAnalyticsService,
    TrainingEfficiencyService
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
        # Automatically add all team players since all sessions are now team sessions
        if session.team:
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
        # Automatically add all team players since all sessions are now team sessions
        if session.team:
            service = TrainingSessionService()
            service.auto_add_team_players(session)
    
    @action(detail=True, methods=['post'])
    def assign_metrics(self, request, pk=None):
        """Assign specific metrics to a training session and create records for all players"""
        from .services import TrainingSessionService
        
        session = self.get_object()
          # Check if metrics can be configured for this session
        if not session.can_configure_metrics():
            return Response({
                "detail": f"Metrics cannot be configured for {session.status} sessions. Only upcoming and ongoing sessions allow metrics configuration.",
                "session_status": session.status,
                "auto_status": session.get_auto_status()
            }, status=status.HTTP_400_BAD_REQUEST)
        
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
    
    @action(detail=True, methods=['post'])
    def assign_metrics_to_players(self, request, pk=None):
        """Assign specific metrics to specific players in a training session"""
        from .services import TrainingSessionService
        
        session = self.get_object()
        
        # Check if metrics can be configured for this session
        if not session.can_configure_metrics():
            return Response({
                "detail": f"Metrics cannot be configured for {session.status} sessions. Only upcoming and ongoing sessions allow metrics configuration.",
                "session_status": session.status,
                "auto_status": session.get_auto_status()
            }, status=status.HTTP_400_BAD_REQUEST)
        
        player_ids = request.data.get('player_ids', [])
        metric_ids = request.data.get('metric_ids', [])
        
        if not isinstance(player_ids, list) or not player_ids:
            return Response(
                {"detail": "Player IDs must be provided as a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not isinstance(metric_ids, list) or not metric_ids:
            return Response(
                {"detail": "Metric IDs must be provided as a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST
            )
        service = TrainingSessionService()
        result = service.assign_metrics_to_players_in_session(session, player_ids, metric_ids)
        
        # Build descriptive message
        total_added = result.get('total_metrics_added', 0)
        total_removed = result.get('total_metrics_removed', 0)
        players_processed = result.get('total_players_processed', 0)
        
        return Response({
            "detail": f"Processed {players_processed} players - {total_added} metrics added, {total_removed} metrics removed",
            "total_players_processed": players_processed,
            "total_metrics_added": total_added,
            "total_metrics_removed": total_removed,
            "assigned_players": len(player_ids),
            "assigned_metrics": len(metric_ids),
            "success": result.get('success', True),
            "player_results": result.get('results', [])
        })
    
    @action(detail=True, methods=['post'])
    def start_training(self, request, pk=None):
        """Manually start a training session (change status from UPCOMING to ONGOING)"""
        session = self.get_object()
        
        # Check if session can be started
        if session.status != session.Status.UPCOMING:
            return Response({
                "detail": f"Training session cannot be started. Current status: {session.status}. Only upcoming sessions can be started.",
                "session_status": session.status,
                "auto_status": session.get_auto_status()
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if user has permission to start this session
        user = request.user
        if not (user.is_admin or (hasattr(user, 'coach_profile') and session.team in user.coach_profile.teams.all())):
            return Response({
                "detail": "You don't have permission to start this training session."
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Update session status to ONGOING
        session.status = session.Status.ONGOING
        session.save(update_fields=['status'])
        return Response({
            "detail": "Training session started successfully.",
            "session_status": session.status,
            "auto_status": session.get_auto_status(),
            "session_id": session.id,
            "session_title": session.title
        })
    
    @action(detail=True, methods=['post'])
    def end_training(self, request, pk=None):
        """Manually end a training session (change status from ONGOING to COMPLETED)"""
        session = self.get_object()
        
        # Check if session can be ended
        if session.status != session.Status.ONGOING:
            return Response({
                "detail": f"Training session cannot be ended. Current status: {session.status}. Only ongoing sessions can be ended.",
                "session_status": session.status,
                "auto_status": session.get_auto_status()
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if user has permission to end this session
        user = request.user
        if not (user.is_admin or (hasattr(user, 'coach_profile') and session.team in user.coach_profile.teams.all())):
            return Response({
                "detail": "You don't have permission to end this training session."
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Update session status to COMPLETED
        session.status = session.Status.COMPLETED
        session.save(update_fields=['status'])
        
        return Response({
            "detail": "Training session ended successfully.",
            "session_status": session.status,
            "auto_status": session.get_auto_status(),
            "session_id": session.id,
            "session_title": session.title
        })
    
    @action(detail=True, methods=['post'])
    def assign_metrics_to_players(self, request, pk=None):
        """Assign specific metrics to specific players in a training session"""
        from .services import TrainingSessionService
        
        session = self.get_object()
        
        # Check if metrics can be configured for this session
        if not session.can_configure_metrics():
            return Response({
                "detail": f"Metrics cannot be configured for {session.status} sessions. Only upcoming and ongoing sessions allow metrics configuration.",
                "session_status": session.status,
                "auto_status": session.get_auto_status()
            }, status=status.HTTP_400_BAD_REQUEST)
        
        player_ids = request.data.get('player_ids', [])
        metric_ids = request.data.get('metric_ids', [])
        if not isinstance(player_ids, list) or not isinstance(metric_ids, list):
            return Response(
                {"detail": "player_ids and metric_ids must be provided as lists"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not player_ids:
            return Response(
                {"detail": "player_ids must be a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST
            )
        service = TrainingSessionService()
        result = service.assign_metrics_to_players_in_session(session, player_ids, metric_ids)
        
        # Create appropriate response message based on operation
        if len(metric_ids) == 0:
            message = f"Removed all metrics from {len(player_ids)} players"
        else:
            message = f"Assigned {len(metric_ids)} metrics to {len(player_ids)} players"
            
        return Response({
            "detail": message,
            "player_count": len(player_ids),
            "metric_count": len(metric_ids),
            "assigned_records": result.get('total_assigned', 0),
            "results": result.get('results', [])
        })

    @action(detail=True, methods=['post'])
    def assign_metrics_to_single_player(self, request, pk=None):
        """Assign specific metrics to a single player in a training session"""
        from .services import TrainingSessionService
        
        session = self.get_object()
        
        # Check if metrics can be configured for this session
        if not session.can_configure_metrics():
            return Response({
                "detail": f"Metrics cannot be configured for {session.status} sessions. Only upcoming and ongoing sessions allow metrics configuration.",
                "session_status": session.status,
                "auto_status": session.get_auto_status()
            }, status=status.HTTP_400_BAD_REQUEST)
        
        player_id = request.data.get('player_id')
        metric_ids = request.data.get('metric_ids', [])
        
        if not player_id:
            return Response(
                {"detail": "player_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not isinstance(metric_ids, list):
            return Response(
                {"detail": "metric_ids must be provided as a list"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not metric_ids:
            return Response(
                {"detail": "metric_ids must be a non-empty list for single player assignment"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        service = TrainingSessionService()
        result = service.assign_metrics_to_single_player(session, player_id, metric_ids)
        
        if not result.get('success'):
            return Response({
                "detail": result.get('message', 'Failed to assign metrics'),
                "success": False
            }, status=status.HTTP_400_BAD_REQUEST)        # Create professional message based on operation results
        metrics_added = result.get('metrics_added', 0)
        metrics_removed = result.get('metrics_removed', 0)
        
        if metrics_added > 0 and metrics_removed > 0:
            detail_message = f"Successfully updated player metrics: {metrics_added} metrics assigned and {metrics_removed} metrics removed."
        elif metrics_added > 0:
            detail_message = f"Successfully assigned {metrics_added} metric{'s' if metrics_added != 1 else ''} to player."
        elif metrics_removed > 0:
            detail_message = f"Successfully removed {metrics_removed} metric{'s' if metrics_removed != 1 else ''} from player."
        else:
            detail_message = "Player metrics configuration updated successfully."
        
        return Response({
            "detail": detail_message,
            "metrics_added": metrics_added,
            "metrics_removed": metrics_removed,
            "success": True,
            "player_id": player_id,
            "metric_count": len(metric_ids),
            "result": result
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
        session = player_training.session
        
        # Check if metrics can be recorded for this session
        if not session.can_record_metrics():
            return Response({
                "detail": f"Metrics cannot be recorded for {session.status} sessions. Only ongoing and completed sessions allow metrics recording.",
                "session_status": session.status,
                "auto_status": session.get_auto_status()
            }, status=status.HTTP_400_BAD_REQUEST)
        
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
        session = player_training.session        # Check if attendance can be managed for this session
        if not session.can_manage_attendance():
            return Response({
                "detail": f"Attendance cannot be managed for {session.status} sessions. Only ongoing sessions or completed sessions within 24 hours allow attendance management.",
                "session_status": session.status,
                "auto_status": session.get_auto_status()
            }, status=status.HTTP_400_BAD_REQUEST)
        
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
            return Response({"detail": "No player records provided."}, status=status.HTTP_400_BAD_REQUEST)        # Check session status before updating attendance
        try:
            session = TrainingSession.objects.get(id=session_id)
            if not session.can_manage_attendance():
                return Response({
                    "detail": f"Attendance cannot be managed for {session.status} sessions. Only ongoing sessions or completed sessions within 24 hours allow attendance management.",
                    "session_status": session.status,
                    "auto_status": session.get_auto_status()
                }, status=status.HTTP_400_BAD_REQUEST)
        except TrainingSession.DoesNotExist:
            return Response({"detail": "Training session not found."}, status=status.HTTP_404_NOT_FOUND)
        
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
    
    def perform_create(self, serializer):
        """Validate session status before creating metric records"""
        player_training = serializer.validated_data.get('player_training')
        session = player_training.session
        
        # Check if metrics can be recorded for this session
        if not session.can_record_metrics():
            raise ValidationError({
                'detail': f'Metrics cannot be recorded for {session.status} sessions. Only ongoing and completed sessions allow metrics recording.',
                'session_status': session.status,
                'auto_status': session.get_auto_status()
            })
        
        # Validate team permissions for coaches
        if self.request.user.is_admin:
            # Admins can create metric records for any team
            serializer.save(recorded_by_id=getattr(self.request.user, 'coach_profile_id', None))
        elif self.request.user.is_coach and hasattr(self.request.user, 'coach_profile'):
            # Coaches can only create metric records for their team's players
            coach_teams = list(self.request.user.coach_profile.teams.all())
            
            # Check if the metric record belongs to one of the coach's teams
            if session.team and session.team in coach_teams:
                serializer.save(recorded_by=self.request.user.coach_profile)
            else:
                raise PermissionDenied("You can only create metric records for your own team's players")
        else:
            raise PermissionDenied("You don't have permission to create metric records")
    
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
            return base_queryset.filter(team__in=coach_teams)        # For players, show only their own data
        if hasattr(user, 'player_profile'):
            return base_queryset.filter(user_id=user.id)

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

    @action(detail=False, methods=['get'])
    def player_radar_chart(self, request):
        """Get radar chart data for a player's performance across training categories"""
        from django.db.models import Avg, Max, Min, Count
        from decimal import Decimal
        from django.utils.dateparse import parse_date
        
        player_id = request.query_params.get('player_id')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        
        if not player_id:
            return Response(
                {"detail": "player_id parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            player = Player.objects.get(user_id=player_id)
        except Player.DoesNotExist:
            return Response(
                {"detail": "Player not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Apply role-based access control
        user = request.user
        if not user.is_admin:
            # For coaches, check if player is in their teams
            if hasattr(user, 'coach_profile'):
                coach_teams = user.coach_profile.teams.all()
                if player.team not in coach_teams:
                    raise PermissionDenied("You can only access radar chart data for players in your teams")
            # For players, check if they're accessing their own data
            elif hasattr(user, 'player_profile'):
                if player != user.player_profile:
                    raise PermissionDenied("You can only access your own radar chart data")
            else:
                raise PermissionDenied("You don't have permission to access radar chart data")
        
        # Build base query for player's metric records
        records_query = PlayerMetricRecord.objects.filter(
            player_training__player=player
        ).select_related(
            'metric__category',
            'metric__metric_unit',
            'player_training__session'
        )
        
        # Apply date filters if provided
        if date_from:
            try:
                date_from_parsed = parse_date(date_from)
                records_query = records_query.filter(
                    player_training__session__date__gte=date_from_parsed
                )
            except (ValueError, TypeError):
                return Response(
                    {"detail": "Invalid date_from format. Use YYYY-MM-DD"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        if date_to:
            try:
                date_to_parsed = parse_date(date_to)
                records_query = records_query.filter(
                    player_training__session__date__lte=date_to_parsed
                )
            except (ValueError, TypeError):
                return Response(
                    {"detail": "Invalid date_to format. Use YYYY-MM-DD"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Get all training categories with metrics for this player
        categories_with_data = []
        categories = TrainingCategory.objects.filter(
            metrics__records__player_training__player=player
        ).distinct()
        
        for category in categories:
            # Get all records for metrics in this category
            category_records = records_query.filter(
                metric__category=category
            ).order_by('player_training__session__date')
            
            if not category_records.exists():
                continue
            
            # Calculate performance metrics for this category
            category_metrics = []
            metrics_in_category = TrainingMetric.objects.filter(
                category=category,
                records__player_training__player=player
            ).distinct()
            
            total_improvement = 0
            metrics_with_improvement = 0
            latest_performance_score = 0
            
            for metric in metrics_in_category:
                metric_records = category_records.filter(metric=metric)
                
                if metric_records.count() < 2:
                    continue
                
                # Get first and latest records for improvement calculation
                first_record = metric_records.first()
                latest_record = metric_records.last()
                
                first_value = float(first_record.value)
                latest_value = float(latest_record.value)
                
                # Calculate improvement percentage
                if first_value != 0:
                    raw_improvement = ((latest_value - first_value) / first_value) * 100
                    
                    # Apply normalization and direction logic
                    normalization_weight = 1.0
                    if metric.metric_unit:
                        normalization_weight = float(metric.metric_unit.normalization_weight)
                    
                    improvement = raw_improvement * normalization_weight
                    
                    # For metrics where lower is better, invert the improvement
                    if metric.is_lower_better:
                        improvement = -improvement
                    
                    total_improvement += improvement
                    metrics_with_improvement += 1
                    
                    # Calculate latest performance score (0-100 scale)
                    # This is a normalized score based on improvement
                    performance_score = max(0, min(100, 50 + (improvement / 2)))
                    latest_performance_score += performance_score
                
                category_metrics.append({
                    'metric_name': metric.name,
                    'metric_unit': metric.metric_unit.code if metric.metric_unit else '',
                    'latest_value': float(latest_record.value),
                    'improvement_percentage': improvement if first_value != 0 else 0,
                    'records_count': metric_records.count()
                })
            
            # Calculate category averages
            avg_improvement = (total_improvement / metrics_with_improvement) if metrics_with_improvement > 0 else 0
            avg_performance_score = (latest_performance_score / metrics_with_improvement) if metrics_with_improvement > 0 else 50
            
            categories_with_data.append({
                'category_id': category.id,
                'category_name': category.name,
                'description': category.description,
                'average_improvement': round(avg_improvement, 2),
                'performance_score': round(avg_performance_score, 2),
                'metrics_count': metrics_with_improvement,
                'total_records': category_records.count(),
                'metrics_data': category_metrics
            })
        
        # Prepare radar chart data
        chart_data = {
            'player_id': player_id,
            'player_name': f"{player.user.first_name} {player.user.last_name}",
            'categories': categories_with_data,
            'chart_labels': [cat['category_name'] for cat in categories_with_data],
            'performance_scores': [cat['performance_score'] for cat in categories_with_data],
            'improvement_percentages': [cat['average_improvement'] for cat in categories_with_data],
            'date_range': {
                'from': date_from,
                'to': date_to
            },
            'summary': {
                'categories_tracked': len(categories_with_data),
                'total_metrics': sum(cat['metrics_count'] for cat in categories_with_data),
                'overall_performance': round(sum(cat['performance_score'] for cat in categories_with_data) / len(categories_with_data), 2) if categories_with_data else 0,
                'overall_improvement': round(sum(cat['average_improvement'] for cat in categories_with_data) / len(categories_with_data), 2) if categories_with_data else 0
            }
        }
        
        return Response(chart_data)

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
            base_queryset = self.get_base_queryset(request)
            filters = self._get_filters(request)
            
            # Use service to calculate overview analytics
            data = AttendanceAnalyticsService.calculate_attendance_overview(
                base_queryset, filters
            )
            
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
            base_queryset = self.get_base_queryset(request)
            filters = self._get_filters(request)
            
            # Use service to calculate trends
            trends_data = AttendanceAnalyticsService.calculate_attendance_trends(
                base_queryset, filters
            )
            
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
            base_queryset = self.get_base_queryset(request)
            filters = self._get_filters(request)
            
            # Use service to calculate heatmap
            heatmap_data = AttendanceAnalyticsService.calculate_attendance_heatmap(
                base_queryset, filters
            )
            
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
            base_queryset = self.get_base_queryset(request)
            filters = self._get_filters(request)
            
            # Use service to calculate player analytics
            players_data = AttendanceAnalyticsService.calculate_player_attendance_analytics(
                base_queryset, filters
            )
            
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
            
            base_queryset = self.get_base_queryset(request)
            filters = self._get_filters(request)
            user = request.user
              # Use service to get player detail analytics
            data = AttendanceAnalyticsService.get_player_detail_analytics(
                player_id, base_queryset, filters, user
            )
            
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
        return AttendanceAnalyticsService.get_filters(request)

    @action(detail=True, methods=['post'])
    def assign_metrics_to_players(self, request, pk=None):
        """Assign specific metrics to specific players in a training session"""
        from .services import TrainingSessionService
        
        session = self.get_object()
        
        # Check if metrics can be configured for this session
        if not session.can_configure_metrics():
            return Response({
                "detail": f"Metrics cannot be configured for {session.status} sessions. Only upcoming and ongoing sessions allow metrics configuration.",
                "session_status": session.status,
                "auto_status": session.get_auto_status()
            }, status=status.HTTP_400_BAD_REQUEST)
        
        player_ids = request.data.get('player_ids', [])
        metric_ids = request.data.get('metric_ids', [])
        if not isinstance(player_ids, list) or not isinstance(metric_ids, list):
            return Response(
                {"detail": "player_ids and metric_ids must be provided as lists"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not player_ids:
            return Response(
                {"detail": "player_ids must be a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST
            )
        service = TrainingSessionService()
        result = service.assign_metrics_to_players_in_session(session, player_ids, metric_ids)
        
        # Calculate totals from the results
        total_added = sum(player_result.get('created_records', 0) for player_result in result.get('results', []))
        total_removed = sum(player_result.get('deleted_records', 0) for player_result in result.get('results', []))
        players_processed = result.get('total_players_processed', 0)
        return Response({
            "detail": f"Processed {players_processed} players - {total_added} metrics added, {total_removed} metrics removed",
            "total_players_processed": players_processed,
            "total_metrics_added": total_added,
            "total_metrics_removed": total_removed,            "player_count": len(player_ids),
            "metric_count": len(metric_ids),
            "success": result.get('success', True),
            "results": result.get('results', [])
        })
