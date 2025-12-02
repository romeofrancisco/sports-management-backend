from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError
from sports_management.permissions import IsAdminUser, IsCoachUser, IsAdminOrCoachUser
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Avg, Max, Min, Q
from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.core.exceptions import PermissionDenied
import logging
import time


def get_coach_teams(coach_profile):
    """Helper function to get teams where coach is either head coach or assistant coach"""
    from teams.models import Team

    return Team.objects.filter(
        Q(head_coach=coach_profile) | Q(assistant_coach=coach_profile)
    )


def is_coach_team(team, coach_profile):
    """Helper function to check if a team belongs to a coach"""
    from teams.models import Team

    return Team.objects.filter(
        Q(head_coach=coach_profile) | Q(assistant_coach=coach_profile), id=team.id
    ).exists()


from .models import (
    MetricUnit,
    TrainingCategory,
    TrainingSession,
    PlayerTraining,
    TrainingMetric,
    PlayerMetricRecord,
)
from .services.attendance_analytics_service import (
    AttendanceAnalyticsService,
    TeamAnalyticsService,
    TrainingEfficiencyService,
)
from .filters import TrainingSessionFilter, PlayerTrainingFilter
from .serializers import (
    MetricUnitSerializer,
    TrainingCategorySerializer,
    TrainingSessionListSerializer,
    TrainingSessionDetailSerializer,
    TrainingSessionInfoSerializer,
    TrainingSessionWorkflowSerializer,
    TrainingSessionAttendanceSerializer,
    TrainingSessionMetricsConfigSerializer,
    PlayerTrainingSerializer,
    TrainingMetricSerializer,
    PlayerMetricRecordSerializer,
    PlayerProgressSerializer,
)
from .services.attendance_analytics_service import (
    AttendanceAnalyticsService,
    TeamAnalyticsService,
    TrainingEfficiencyService,
)
from teams.models import Player, Team
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, F
from django.utils.dateparse import parse_date


class TrainingPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100


class MetricUnitViewSet(viewsets.ModelViewSet):
    queryset = MetricUnit.objects.all().order_by("name")
    serializer_class = MetricUnitSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "code", "description"]

    def get_queryset(self):
        """
        Return metric units based on user role:
        - Admin: All metric units
        - Coach: Only admin-created units (system defaults) and their own units
        - Others: Only admin-created units (system defaults)
        """
        user = self.request.user
        base_queryset = MetricUnit.objects.all().order_by("name")

        # Admin can see all units
        if user.is_admin:
            return base_queryset
        
        # Coach can see admin-created units (system defaults) and their own units
        if hasattr(user, 'coach_profile') and user.is_coach:
            return base_queryset.filter(
                Q(is_default=True) | Q(created_by=user)
            )
        
        # Others (players, etc.) can only see admin-created units (system defaults)
        return base_queryset.filter(is_default=True)

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        - GET requests are accessible to authenticated users
        - POST/PUT/PATCH/DELETE requests are restricted to admin and coach users
        """
        if self.action in ["create", "update", "partial_update", "destroy"]:
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
    search_fields = ["name", "description"]

    def get_queryset(self):
        """
        Return training categories based on user role:
        - Admin: All training categories
        - Coach: Only admin-created categories (system defaults) and their own categories
        - Others: Only admin-created categories (system defaults)
        """
        user = self.request.user
        base_queryset = TrainingCategory.objects.all().order_by("name")

        # Admin can see all categories
        if user.is_admin:
            return base_queryset
        
        # Coach can see admin-created categories (system defaults) and their own categories
        if hasattr(user, 'coach_profile') and user.is_coach:
            return base_queryset.filter(
                Q(is_default=True) | Q(created_by=user)
            )
        
        # Others (players, etc.) can only see admin-created categories (system defaults)
        return base_queryset.filter(is_default=True)

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        - GET requests are accessible to authenticated users
        - POST/PUT/PATCH/DELETE requests are restricted to admin and coach users
        """
        if self.action in ["create", "update", "partial_update", "destroy"]:
            permission_classes = [IsAdminOrCoachUser]
        else:
            permission_classes = [IsAuthenticated]

        return [permission() for permission in permission_classes]

    def perform_create(self, serializer):
        """Set creation logic based on user role"""
        user = self.request.user

        # Admin-created categories are automatically system defaults
        if user.is_admin:
            serializer.save(created_by=user, is_default=True)
        # Coach-created categories are not system defaults
        else:
            serializer.save(created_by=user, is_default=False)

    def perform_update(self, serializer):
        """Allow updates based on user role and ownership"""
        user = self.request.user
        instance = serializer.instance

        # Admin can update any category
        if user.is_admin:
            serializer.save()
        # Coach can only update categories they created (non-default)
        elif user.is_coach:
            if instance.is_default:
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("Coaches cannot edit system default categories")
            if instance.created_by != user:
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("You can only edit categories you created")
            serializer.save()
        else:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You don't have permission to update training categories")

    def perform_destroy(self, instance):
        """Allow deletion based on user role and ownership"""
        user = self.request.user

        # Admin can delete any category (including system defaults)
        if user.is_admin:
            instance.delete()
        # Coach can only delete categories they created (non-default)
        elif user.is_coach:
            if instance.is_default:
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("Coaches cannot delete system default categories")
            if instance.created_by != user:
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("You can only delete categories you created")
            instance.delete()
        else:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You don't have permission to delete training categories")


class TrainingMetricViewSet(viewsets.ModelViewSet):
    queryset = TrainingMetric.objects.all()
    serializer_class = TrainingMetricSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["category", "sessions"]
    search_fields = ["name", "description"]

    def get_queryset(self):
        """
        Return training metrics based on user role:
        - Admin: All training metrics
        - Coach: Only admin-created metrics (system defaults) and their own metrics
        - Others: Only admin-created metrics (system defaults)
        """
        user = self.request.user
        base_queryset = TrainingMetric.objects.all().order_by("name")

        # Admin can see all metrics
        if user.is_admin:
            return base_queryset
        
        # Coach can see admin-created metrics (system defaults) and their own metrics
        if hasattr(user, 'coach_profile') and user.is_coach:
            return base_queryset.filter(
                Q(is_default=True) | Q(created_by=user)
            )
        
        # Others (players, etc.) can only see admin-created metrics (system defaults)
        return base_queryset.filter(is_default=True)

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        - GET requests are accessible to authenticated users
        - POST/PUT/PATCH/DELETE requests are restricted to admin and coach users
        """
        if self.action in ["create", "update", "partial_update", "destroy"]:
            permission_classes = [IsAdminOrCoachUser]
        else:
            permission_classes = [IsAuthenticated]

        return [permission() for permission in permission_classes]

    def perform_create(self, serializer):
        """Set creation logic based on user role"""
        user = self.request.user

        # Admin-created metrics are automatically system defaults
        if user.is_admin:
            serializer.save(created_by=user, is_default=True)
        # Coach-created metrics are not system defaults
        else:
            serializer.save(created_by=user, is_default=False)

    def perform_update(self, serializer):
        """Allow updates based on user role and ownership"""
        user = self.request.user
        instance = serializer.instance

        # Admin can update any metric
        if user.is_admin:
            serializer.save()
        # Coach can only update metrics they created (non-default)
        elif user.is_coach:
            if instance.is_default:
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("Coaches cannot edit system default metrics")
            if instance.created_by != user:
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("You can only edit metrics you created")
            serializer.save()
        else:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You don't have permission to update training metrics")

    def perform_destroy(self, instance):
        """Allow deletion based on user role and ownership"""
        user = self.request.user

        # Admin can delete any metric (including system defaults)
        if user.is_admin:
            instance.delete()
        # Coach can only delete metrics they created (non-default)
        elif user.is_coach:
            if instance.is_default:
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("Coaches cannot delete system default metrics")
            if instance.created_by != user:
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("You can only delete metrics you created")
            instance.delete()
        else:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You don't have permission to delete training metrics")


class TrainingSessionViewSet(viewsets.ModelViewSet):
    queryset = TrainingSession.objects.all().order_by("-date", "-start_time")
    permission_classes = [IsAuthenticated]
    pagination_class = TrainingPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = TrainingSessionFilter
    search_fields = ["title", "description", "location"]

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
        base_queryset = TrainingSession.objects.all().order_by("-date", "-start_time")

        # For admins, show all training sessions
        if user.is_admin:
            return (
                base_queryset  # For coaches, show only their team's training sessions
            )
        if hasattr(user, "coach_profile"):
            from django.db.models import Q
            from teams.models import Team

            coach_teams = Team.objects.filter(
                Q(head_coach=user.coach_profile) | Q(assistant_coach=user.coach_profile)
            )
            return base_queryset.filter(team__in=coach_teams)

        # For players, show only their team's training sessions
        if hasattr(user, "player_profile") and user.player_profile.team:
            player_team = user.player_profile.team
            return base_queryset.filter(team=player_team)

        # User doesn't have appropriate role - deny access
        raise PermissionDenied(
            "You don't have permission to access training session data"
        )

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
            raise PermissionDenied(
                "You don't have permission to access this training session"
            )

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
        if self.action in ["create", "update", "partial_update", "destroy"]:
            permission_classes = [IsAdminOrCoachUser]
        else:
            permission_classes = [IsAuthenticated]

        return [permission() for permission in permission_classes]

    def get_serializer_class(self):
        if self.action == "list":
            return TrainingSessionListSerializer
        return TrainingSessionDetailSerializer

    def list(self, request, *args, **kwargs):
        # Log the request parameters for debugging
        logger = logging.getLogger(__name__)
        logger.info(f"Training session list - Query params: {request.query_params}")

        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        from .services import TrainingSessionService
        from notifications.utils import send_training_session_notification

        # For coaches, ensure they can only create sessions for their teams
        if self.request.user.is_coach:
            team = serializer.validated_data.get("team")
            if team:
                from django.db.models import Q
                from teams.models import Team

                coach_teams = Team.objects.filter(
                    Q(head_coach=self.request.user.coach_profile)
                    | Q(assistant_coach=self.request.user.coach_profile)
                )
                if team not in coach_teams:
                    raise PermissionDenied(
                        "You can only create training sessions for your own teams"
                    )
                    
        creator = self.request.user or (team.head_coach if team else None)

        session = serializer.save(creator=creator)
        # Automatically add all team players since all sessions are now team sessions
        if session.team:
            service = TrainingSessionService()
            service.auto_add_team_players(session)
            
            # Send push notification to all players in the team
            try:
                send_training_session_notification(session, creator=self.request.user)
            except Exception as e:
                # Log error but don't fail the request
                print(f"[DEBUG] Failed to send training session notification: {e}")
                import traceback
                traceback.print_exc()

    def perform_update(self, serializer):
        """Only allow coaches to update training sessions for their own teams"""
        from notifications.utils import send_training_session_notification
        
        if self.request.user.is_admin:  # Admins can update any training session
            session = serializer.save()
            # Send update notification
            try:
                send_training_session_notification(session, creator=self.request.user, is_update=True)
            except Exception as e:
                print(f"[DEBUG] Failed to send training session update notification: {e}")
        elif self.request.user.is_coach and hasattr(self.request.user, "coach_profile"):
            # Coaches can only update training sessions for their teams
            from django.db.models import Q
            from teams.models import Team

            coach_teams = Team.objects.filter(
                Q(head_coach=self.request.user.coach_profile)
                | Q(assistant_coach=self.request.user.coach_profile)
            )
            session = serializer.instance

            # Check if the session belongs to one of the coach's teams
            if session.team and session.team in coach_teams:
                # Also check if they're trying to change the team to one they don't coach
                new_team = serializer.validated_data.get("team", session.team)
                if new_team not in coach_teams:
                    raise PermissionDenied(
                        "You can only assign training sessions to your own teams"
                    )
                session = serializer.save()
                # Send update notification
                try:
                    send_training_session_notification(session, creator=self.request.user, is_update=True)
                except Exception as e:
                    print(f"[DEBUG] Failed to send training session update notification: {e}")
            else:
                raise PermissionDenied(
                    "You can only update training sessions for your own teams"
                )
        else:
            raise PermissionDenied(
                "You don't have permission to update training sessions"
            )

    def perform_destroy(self, instance):
        """Only allow coaches to delete training sessions for their own teams"""
        if self.request.user.is_admin:  # Admins can delete any training session
            instance.delete()
        elif self.request.user.is_coach and hasattr(self.request.user, "coach_profile"):
            # Coaches can only delete training sessions for their teams
            coach_teams = get_coach_teams(self.request.user.coach_profile)

            # Check if the session belongs to one of the coach's teams
            if instance.team and instance.team in coach_teams:
                instance.delete()
            else:
                raise PermissionDenied(
                    "You can only delete training sessions for your own teams"
                )
        else:
            raise PermissionDenied(
                "You don't have permission to delete training sessions"
            )

    @action(detail=True, methods=["post"])
    def add_players(self, request, pk=None):
        """Add multiple players to a training session"""
        from .services import TrainingSessionService

        session = self.get_object()
        player_ids = request.data.get("player_ids", [])
        attendance_status = request.data.get("attendance_status", "present")

        service = TrainingSessionService()
        result = service.add_players_to_session(session, player_ids, attendance_status)

        return Response(
            {
                "detail": f"Added {result['added_count']} players to training session",
                "added_count": result["added_count"],
            }
        )

    @action(detail=True, methods=["get"])
    def analytics(self, request, pk=None):
        """Get analytics for a specific training session"""
        from .services import TrainingSessionService

        session = self.get_object()
        service = TrainingSessionService()
        analytics_data = service.get_session_analytics(session)
        return Response(analytics_data)

    @action(detail=True, methods=["get"], url_path="info")
    def session_info(self, request, pk=None):
        """Get lightweight session information without heavy player/metrics data"""
        session = self.get_object()

        # Use the lightweight serializer
        serializer = TrainingSessionInfoSerializer(
            session, context={"request": request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="workflow")
    def session_workflow(self, request, pk=None):
        """Get basic session data for workflow management"""
        session = self.get_object()

        # Use the workflow serializer (just basic session info for workflow stepper)
        serializer = TrainingSessionWorkflowSerializer(
            session, context={"request": request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="attendance")
    def session_attendance(self, request, pk=None):
        """Get session data for attendance management"""
        session = self.get_object()

        # Use the attendance serializer (session info + lightweight player attendance data)
        serializer = TrainingSessionAttendanceSerializer(
            session, context={"request": request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="metrics-config")
    def session_metrics_config(self, request, pk=None):
        """Get session data for metrics configuration"""
        session = self.get_object()

        # Use the metrics config serializer (session info + categories + basic players list)
        serializer = TrainingSessionMetricsConfigSerializer(
            session, context={"request": request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def assign_metrics(self, request, pk=None):
        """Assign specific metrics to a training session and create records for all players"""
        from .services import TrainingSessionService

        session = self.get_object()
        # Check if metrics can be configured for this session
        if not session.can_configure_metrics():
            return Response(
                {
                    "detail": f"Metrics cannot be configured for {session.status} sessions. Only upcoming and ongoing sessions allow metrics configuration.",
                    "session_status": session.status,
                    "auto_status": session.get_auto_status(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        metric_ids = request.data.get("metrics", [])

        if not isinstance(metric_ids, list):
            return Response(
                {"detail": "Metrics must be provided as a list of IDs"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        service = TrainingSessionService()
        result = service.assign_metrics_to_session(session, metric_ids)
        return Response(
            {
                "detail": f"Assigned {result['assigned_count']} metrics to training session",
                "count": result["assigned_count"],
                "invalid_metrics": result.get("invalid_metrics"),
                "created_records": result.get("total_created_records", 0),
                "updated_records": result.get("total_deleted_records", 0),
                "player_results": result.get("player_results", []),
            }
        )

    @action(detail=True, methods=["post"])
    def assign_metrics_to_players(self, request, pk=None):
        """Assign specific metrics to specific players in a training session"""
        from .services import TrainingSessionService

        session = self.get_object()

        # Check if metrics can be configured for this session
        if not session.can_configure_metrics():
            return Response(
                {
                    "detail": f"Metrics cannot be configured for {session.status} sessions. Only upcoming and ongoing sessions allow metrics configuration.",
                    "session_status": session.status,
                    "auto_status": session.get_auto_status(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        player_ids = request.data.get("player_ids", [])
        metric_ids = request.data.get("metric_ids", [])

        if not isinstance(player_ids, list) or not player_ids:
            return Response(
                {"detail": "Player IDs must be provided as a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(metric_ids, list) or not metric_ids:
            return Response(
                {"detail": "Metric IDs must be provided as a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        service = TrainingSessionService()
        result = service.assign_metrics_to_players_in_session(
            session, player_ids, metric_ids
        )

        # Build descriptive message
        total_added = result.get("total_metrics_added", 0)
        total_removed = result.get("total_metrics_removed", 0)
        players_processed = result.get("total_players_processed", 0)

        return Response(
            {
                "detail": f"Processed {players_processed} players - {total_added} metrics added, {total_removed} metrics removed",
                "total_players_processed": players_processed,
                "total_metrics_added": total_added,
                "total_metrics_removed": total_removed,
                "assigned_players": len(player_ids),
                "assigned_metrics": len(metric_ids),
                "success": result.get("success", True),
                "player_results": result.get("results", []),
            }
        )

    @action(detail=True, methods=["post"])
    def start_training(self, request, pk=None):
        """Manually start a training session (change status from UPCOMING to ONGOING)"""
        session = self.get_object()

        # Check if session can be started
        if session.status != session.Status.UPCOMING:
            return Response(
                {
                    "detail": f"Training session cannot be started. Current status: {session.status}. Only upcoming sessions can be started.",
                    "session_status": session.status,
                    "auto_status": session.get_auto_status(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if user has permission to start this session
        user = request.user
        if not (
            user.is_admin
            or (
                hasattr(user, "coach_profile")
                and session.team in get_coach_teams(user.coach_profile)
            )
        ):
            return Response(
                {"detail": "You don't have permission to start this training session."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Update session status to ONGOING
        session.status = session.Status.ONGOING
        session.save(update_fields=["status"])
        return Response(
            {
                "detail": "Training session started successfully.",
                "session_status": session.status,
                "auto_status": session.get_auto_status(),
                "session_id": session.id,
                "session_title": session.title,
            }
        )

    @action(detail=True, methods=["post"])
    def end_training(self, request, pk=None):
        """Manually end a training session (change status from ONGOING to COMPLETED)"""
        from .services.training_completion_service import TrainingCompletionService

        session = self.get_object()

        # Check if session can be ended
        if session.status != session.Status.ONGOING:
            return Response(
                {
                    "detail": f"Training session cannot be ended. Current status: {session.status}. Only ongoing sessions can be ended.",
                    "session_status": session.status,
                    "auto_status": session.get_auto_status(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if user has permission to end this session
        user = request.user
        if not (
            user.is_admin
            or (
                hasattr(user, "coach_profile")
                and session.team in get_coach_teams(user.coach_profile)
            )
        ):
            return Response(
                {"detail": "You don't have permission to end this training session."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Update session status to COMPLETED
        session.status = session.Status.COMPLETED
        session.save(update_fields=["status"])

        # Generate training completion summary
        training_summary = TrainingCompletionService.generate_training_summary(
            session, request
        )

        return Response(
            {
                "detail": "Training session ended successfully.",
                "session_status": session.status,
                "auto_status": session.get_auto_status(),
                "session_id": session.id,
                "session_title": session.title,
                "training_summary": training_summary,
            }
        )

    @action(detail=True, methods=["post"])
    def assign_metrics_to_players(self, request, pk=None):
        """Assign specific metrics to specific players in a training session"""
        from .services import TrainingSessionService

        session = self.get_object()

        # Check if metrics can be configured for this session
        if not session.can_configure_metrics():
            return Response(
                {
                    "detail": f"Metrics cannot be configured for {session.status} sessions. Only upcoming and ongoing sessions allow metrics configuration.",
                    "session_status": session.status,
                    "auto_status": session.get_auto_status(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        player_ids = request.data.get("player_ids", [])
        metric_ids = request.data.get("metric_ids", [])
        if not isinstance(player_ids, list) or not isinstance(metric_ids, list):
            return Response(
                {"detail": "player_ids and metric_ids must be provided as lists"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not player_ids:
            return Response(
                {"detail": "player_ids must be a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        service = TrainingSessionService()
        result = service.assign_metrics_to_players_in_session(
            session, player_ids, metric_ids
        )

        # Calculate totals from the results
        total_added = sum(
            player_result.get("created_records", 0)
            for player_result in result.get("results", [])
        )
        total_removed = sum(
            player_result.get("deleted_records", 0)
            for player_result in result.get("results", [])
        )
        players_processed = result.get("total_players_processed", 0)
        return Response(
            {
                "detail": f"Processed {players_processed} players - {total_added} metrics added, {total_removed} metrics removed",
                "total_players_processed": players_processed,
                "total_metrics_added": total_added,
                "total_metrics_removed": total_removed,
                "player_count": len(player_ids),
                "metric_count": len(metric_ids),
                "success": result.get("success", True),
                "results": result.get("results", []),
            }
        )

    @action(detail=True, methods=["post"])
    def start_training(self, request, pk=None):
        """Manually start a training session (change status from UPCOMING to ONGOING)"""
        session = self.get_object()

        # Check if session can be started
        if session.status != session.Status.UPCOMING:
            return Response(
                {
                    "detail": f"Training session cannot be started. Current status: {session.status}. Only upcoming sessions can be started.",
                    "session_status": session.status,
                    "auto_status": session.get_auto_status(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if user has permission to start this session
        user = request.user
        if not (
            user.is_admin
            or (
                hasattr(user, "coach_profile")
                and session.team in get_coach_teams(user.coach_profile)
            )
        ):
            return Response(
                {"detail": "You don't have permission to start this training session."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Update session status to ONGOING
        session.status = session.Status.ONGOING
        session.save(update_fields=["status"])
        return Response(
            {
                "detail": "Training session started successfully.",
                "session_status": session.status,
                "auto_status": session.get_auto_status(),
                "session_id": session.id,
                "session_title": session.title,
            }
        )

    @action(detail=True, methods=["post"])
    def end_training(self, request, pk=None):
        """Manually end a training session (change status from ONGOING to COMPLETED)"""
        from .services.training_completion_service import TrainingCompletionService

        session = self.get_object()

        # Check if session can be ended
        if session.status != session.Status.ONGOING:
            return Response(
                {
                    "detail": f"Training session cannot be ended. Current status: {session.status}. Only ongoing sessions can be ended.",
                    "session_status": session.status,
                    "auto_status": session.get_auto_status(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if user has permission to end this session
        user = request.user
        if not (
            user.is_admin
            or (
                hasattr(user, "coach_profile")
                and session.team in get_coach_teams(user.coach_profile)
            )
        ):
            return Response(
                {"detail": "You don't have permission to end this training session."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Update session status to COMPLETED
        session.status = session.Status.COMPLETED
        session.save(update_fields=["status"])
        # Generate training completion summary
        training_summary = TrainingCompletionService.generate_training_summary(
            session, request
        )

        return Response(
            {
                "detail": "Training session ended successfully.",
                "session_status": session.status,
                "auto_status": session.get_auto_status(),
                "session_id": session.id,
                "session_title": session.title,
                "training_summary": training_summary,
            }
        )

    @action(detail=True, methods=["post"])
    def assign_metrics_to_single_player(self, request, pk=None):
        """Assign specific metrics to a single player in a training session"""
        from .services.training_session_service import TrainingSessionService

        session = self.get_object()

        # Check if metrics can be configured for this session
        if not session.can_configure_metrics():
            return Response(
                {
                    "detail": f"Metrics cannot be configured for {session.status} sessions. Only upcoming and ongoing sessions allow metrics configuration.",
                    "session_status": session.status,
                    "auto_status": session.get_auto_status(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        player_id = request.data.get("player_id")
        metric_ids = request.data.get("metric_ids", [])

        if not player_id:
            return Response(
                {"detail": "player_id is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        if not isinstance(metric_ids, list):
            return Response(
                {"detail": "metric_ids must be provided as a list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            service = TrainingSessionService()
            result = service.assign_metrics_to_single_player(
                session, player_id, metric_ids
            )

            return Response(
                {
                    "detail": f"Successfully assigned {len(metric_ids)} metrics to player",
                    "player_id": player_id,
                    "metric_count": len(metric_ids),
                    "assigned_metrics": result.get("assigned_metrics", []),
                    "removed_metrics": result.get("removed_metrics", []),
                    "success": True,
                }
            )

        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"detail": f"Error assigning metrics: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get"])
    def training_summary(self, request, pk=None):
        """Get training summary for a completed session"""
        from .services.training_completion_service import TrainingCompletionService

        session = self.get_object()

        # Check if session is completed
        if session.status != session.Status.COMPLETED:
            return Response(
                {
                    "detail": f"Training summary is only available for completed sessions. Current status: {session.status}.",
                    "session_status": session.status,
                    "auto_status": session.get_auto_status(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if user has permission to view this session summary
        user = request.user
        if not (
            user.is_admin
            or (
                hasattr(user, "coach_profile")
                and session.team in get_coach_teams(user.coach_profile)
            )
        ):
            return Response(
                {
                    "detail": "You don't have permission to view this training session summary."
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        # Generate training summary
        training_summary = TrainingCompletionService.generate_training_summary(
            session, request
        )
        return Response({"training_summary": training_summary})

    @action(detail=True, methods=["get"], url_path="ai-insights")
    def get_ai_insights(self, request, pk=None):
        """Get AI-powered insights for a specific training session"""
        from .services.training_completion_service import TrainingCompletionService

        session = self.get_object()

        # Check if session is completed
        if session.status != session.Status.COMPLETED:
            return Response(
                {
                    "detail": "AI insights are only available for completed training sessions."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if user has permission to view this session's insights
        user = request.user
        if not (
            user.is_admin
            or (
                hasattr(user, "coach_profile")
                and session.team in get_coach_teams(user.coach_profile)
            )
            or (
                hasattr(user, "player_profile")
                and user.player_profile.team == session.team
            )
        ):
            return Response(
                {
                    "detail": "You don't have permission to view this session's AI insights."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Generate AI insights for this session
        # First get the basic data needed for AI analysis
        attendance_summary = TrainingCompletionService._calculate_attendance_summary(
            session
        )
        metrics_summary = TrainingCompletionService._calculate_metrics_summary(session)
        player_improvements = TrainingCompletionService._calculate_player_improvements(
            session, request
        )
        effectiveness_score = TrainingCompletionService._calculate_effectiveness_score(
            attendance_summary, metrics_summary, player_improvements
        )

        # Generate AI insights
        ai_insights = TrainingCompletionService._generate_ai_insights(
            session,
            attendance_summary,
            metrics_summary,
            player_improvements,
            effectiveness_score,
        )

        return Response(
            {
                "ai_insights": ai_insights,
                "session_id": session.id,
                "session_title": session.title,
                "generated_at": ai_insights.get("generated_at"),
            }
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="teams/(?P<team_id>[^/.]+)/last-session-missed-metrics",
    )
    def last_session_missed_metrics(self, request, team_id=None):
        """Get missed metrics from the last completed training session for a specific team.
        Focuses on absent/excused players who had metrics assigned but didn't record them.

        Query parameters:
        - current_session_id: If provided, get missed metrics from the session before this one
        """
        from teams.models import Team

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return Response(
                {"detail": "Team not found"}, status=status.HTTP_404_NOT_FOUND
            )

        # Check permissions - user should have access to this team
        user = request.user
        if not (
            user.is_admin
            or (
                hasattr(user, "coach_profile")
                and team in get_coach_teams(user.coach_profile)
            )
        ):
            return Response(
                {
                    "detail": "You don't have permission to access this team's training data."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Get current session ID from query parameters
        current_session_id = request.query_params.get("current_session_id")

        # Get the most recent completed training session for this team
        # If current_session_id is provided, get the session before that one
        sessions_query = TrainingSession.objects.filter(
            team=team, status=TrainingSession.Status.COMPLETED
        )

        if current_session_id:
            try:
                current_session = TrainingSession.objects.get(
                    id=current_session_id, team=team
                )
                # Get sessions that were completed before the current session
                sessions_query = sessions_query.filter(
                    models.Q(date__lt=current_session.date)
                    | (
                        models.Q(date=current_session.date)
                        & models.Q(start_time__lt=current_session.start_time)
                    )
                )
            except TrainingSession.DoesNotExist:
                return Response(
                    {
                        "detail": "Current session not found or doesn't belong to this team"
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

        last_session = sessions_query.order_by("-date", "-start_time").first()

        if not last_session:
            return Response(
                {
                    "detail": "No completed training sessions found for this team",
                    "last_session_date": None,
                    "players_with_missed_metrics": [],
                    "total_missed_metrics": 0,
                }
            )

        # Get all player training records from the last session
        # Focus on absent/excused players with assigned metrics
        player_trainings = (
            PlayerTraining.objects.filter(
                session=last_session,
                attendance_status__in=[
                    "absent",
                    "excused",
                ],  # Only absent/excused players
            )
            .select_related("player", "player__user")
            .prefetch_related("assigned_metrics")
        )

        players_with_missed_metrics = []
        total_missed_metrics = 0

        for player_training in player_trainings:
            # Get metrics that were assigned to this player
            assigned_metrics = player_training.assigned_metrics.all()

            if not assigned_metrics.exists():
                continue  # Skip if no metrics were assigned

            # Get metrics recorded by this player (should be none or few for absent/excused)
            recorded_metrics = PlayerMetricRecord.objects.filter(
                player_training=player_training, value__isnull=False
            ).values_list("metric_id", flat=True)

            # Find missed metrics (assigned but not recorded)
            missed_metrics = []
            for metric in assigned_metrics:
                if metric.id not in recorded_metrics:
                    missed_metrics.append(
                        {
                            "metric_id": metric.id,
                            "metric_name": metric.name,
                            "metric_unit": (
                                metric.metric_unit.code if metric.metric_unit else ""
                            ),
                        }
                    )

            if missed_metrics:  # Only include players who missed metrics
                players_with_missed_metrics.append(
                    {
                        "player_id": player_training.player.user.id,
                        "player_name": f"{player_training.player.user.first_name} {player_training.player.user.last_name}",
                        "attendance_status": player_training.attendance_status,
                        "assigned_metrics_count": assigned_metrics.count(),
                        "missed_metrics": missed_metrics,
                    }
                )
                total_missed_metrics += len(missed_metrics)

        return Response(
            {
                "last_session_date": (
                    last_session.date.isoformat() if last_session.date else None
                ),
                "last_session_title": last_session.title,
                "last_session_id": last_session.id,
                "players_with_missed_metrics": players_with_missed_metrics,
                "total_missed_metrics": total_missed_metrics,
                "total_absent_excused_players": player_trainings.count(),
            }
        )


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
        if hasattr(user, "coach_profile"):
            coach_teams = get_coach_teams(user.coach_profile)
            return base_queryset.filter(session__team__in=coach_teams)

        # For players, show only their own training records
        if hasattr(user, "player_profile"):
            return base_queryset.filter(player=user.player_profile)

        # User doesn't have appropriate role - deny access
        raise PermissionDenied(
            "You don't have permission to access player training data"
        )

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
            raise PermissionDenied(
                "You don't have permission to access this player training record"
            )

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
        if self.action in ["create", "update", "partial_update", "destroy"]:
            permission_classes = [IsAdminOrCoachUser]
        else:
            permission_classes = [IsAuthenticated]

        return [permission() for permission in permission_classes]

    def perform_update(self, serializer):
        """Only allow coaches to update player training records for their own team's players"""
        if self.request.user.is_admin:
            # Admins can update any player training record
            serializer.save()
        elif self.request.user.is_coach and hasattr(self.request.user, "coach_profile"):
            # Coaches can only update player training records for their team's players
            coach_teams = get_coach_teams(self.request.user.coach_profile)
            player_training = serializer.instance

            # Check if the player training record belongs to one of the coach's teams
            if (
                player_training.session.team
                and player_training.session.team in coach_teams
            ):
                serializer.save()
            else:
                raise PermissionDenied(
                    "You can only update player training records for your own team's players"
                )
        else:
            raise PermissionDenied(
                "You don't have permission to update player training records"
            )

    def perform_destroy(self, instance):
        """Only allow coaches to delete player training records for their own team's players"""
        if self.request.user.is_admin:
            # Admins can delete any player training record
            instance.delete()
        elif self.request.user.is_coach and hasattr(self.request.user, "coach_profile"):
            # Coaches can only delete player training records for their team's players
            coach_teams = get_coach_teams(self.request.user.coach_profile)

            # Check if the player training record belongs to one of the coach's teams
            if instance.session.team and instance.session.team in coach_teams:
                instance.delete()
            else:
                raise PermissionDenied(
                    "You can only delete player training records for your own team's players"
                )
        else:
            raise PermissionDenied(
                "You don't have permission to delete player training records"
            )

    @action(detail=True, methods=["get"])
    def player_metrics_data(self, request, pk=None):
        """
        Lightweight endpoint to get a specific player's metric data for recording
        Returns only the necessary data without the heavy session object
        """
        player_training = self.get_object()

        # Check permissions
        session = player_training.session
        user = request.user

        # Verify user has access to this session's data
        if not user.is_admin:
            if hasattr(user, "coach_profile"):
                # Coach can only access their team's players
                coach_teams = get_coach_teams(user.coach_profile)
                if session.team not in coach_teams:
                    raise PermissionDenied(
                        "You don't have permission to access this player's data"
                    )
            elif hasattr(user, "player_profile"):
                # Player can only access their own data
                if player_training.player != user.player_profile:
                    raise PermissionDenied("You can only access your own training data")
            else:
                raise PermissionDenied("You don't have permission to access this data")

        # Return lightweight player metrics data
        serializer = PlayerTrainingSerializer(
            player_training, context={"request": request}
        )
        return Response(
            {
                "player_training": serializer.data,
                "session_info": {
                    "id": session.id,
                    "title": session.title,
                    "status": session.status,
                    "can_record_metrics": session.can_record_metrics(),
                },
            }
        )

    @action(detail=False, methods=["get"])
    def session_players_metrics(self, request):
        """
        Lightweight endpoint to get all players' metric data for a specific session
        Returns only the necessary data for metrics recording interface
        """
        session_id = request.query_params.get("session_id")
        if not session_id:
            return Response(
                {"error": "session_id parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            session = TrainingSession.objects.get(id=session_id)
        except TrainingSession.DoesNotExist:
            return Response(
                {"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND
            )

        # Check permissions
        user = request.user
        if not user.is_admin:
            if hasattr(user, "coach_profile"):
                coach_teams = get_coach_teams(user.coach_profile)
                if session.team not in coach_teams:
                    raise PermissionDenied(
                        "You don't have permission to access this session's data"
                    )
            elif hasattr(user, "player_profile"):
                if session.team != user.player_profile.team:
                    raise PermissionDenied(
                        "You can only access your own team's sessions"
                    )
            else:
                raise PermissionDenied("You don't have permission to access this data")

        # Get players with metrics (present/late attendance and assigned metrics)
        players_with_metrics = (
            self.get_queryset()
            .filter(
                session=session,
                attendance_status__in=["present", "late"],
                assigned_metrics__isnull=False,
            )
            .distinct()
        )

        serializer = PlayerTrainingSerializer(
            players_with_metrics, many=True, context={"request": request}
        )

        return Response(
            {
                "session_info": {
                    "id": session.id,
                    "title": session.title,
                    "status": session.status,
                    "can_record_metrics": session.can_record_metrics(),
                },
                "players_with_metrics": serializer.data,
            }
        )

    @action(detail=True, methods=["post"])
    def record_metrics(self, request, pk=None):
        """Record multiple metrics for a player's training"""
        from .services import PlayerTrainingService

        player_training = self.get_object()
        session = player_training.session

        # Check if metrics can be recorded for this session
        if not session.can_record_metrics():
            return Response(
                {
                    "detail": f"Metrics cannot be recorded for {session.status} sessions. Only ongoing and completed sessions allow metrics recording.",
                    "session_status": session.status,
                    "auto_status": session.get_auto_status(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        metrics_data = request.data.get("metrics", [])

        if not metrics_data:
            return Response(
                {"detail": "No metrics data provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = PlayerTrainingService()
        result = service.record_multiple_metrics(
            player_training, metrics_data, request.user
        )

        return Response(
            {
                "detail": f"Recorded {len(result['records'])} metrics",
                "records": result["records"],
                "previous_records": result.get("previous_records", []),
            }
        )

    @action(detail=True, methods=["post"])
    def assign_metrics(self, request, pk=None):
        """Assign specific metrics to a player's training record"""
        from .services import PlayerTrainingService

        player_training = self.get_object()
        metric_ids = request.data.get("metrics", [])

        if not isinstance(metric_ids, list):
            return Response(
                {"detail": "Metrics must be provided as a list of IDs"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = PlayerTrainingService()
        result = service.assign_metrics_to_player_training(player_training, metric_ids)

        return Response(
            {
                "detail": f"Assigned {result['count']} metrics to player training record",
                "count": result["count"],
                "invalid_metrics": result.get("invalid_metrics"),
            }
        )

    def _get_previous_records(self, player_training):
        """Get previous records for this player across metrics"""
        from .services import PlayerTrainingService

        service = PlayerTrainingService()

        return service.get_previous_records(player_training)

    @action(detail=True, methods=["patch"])
    def update_attendance(self, request, pk=None):
        """Update attendance status for a player's training record"""
        from .services import PlayerTrainingService

        player_training = self.get_object()
        session = (
            player_training.session
        )  # Check if attendance can be managed for this session
        if not session.can_manage_attendance():
            return Response(
                {
                    "detail": f"Attendance cannot be managed for {session.status} sessions. Only ongoing sessions or completed sessions within 24 hours allow attendance management.",
                    "session_status": session.status,
                    "auto_status": session.get_auto_status(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_status = request.data.get("attendance_status")
        notes = request.data.get("notes", player_training.notes)

        service = PlayerTrainingService()
        result = service.update_attendance(player_training, new_status, notes)
        return Response(
            {
                "detail": "Attendance updated.",
                "attendance_status": result["attendance_status"],
                "notes": result["notes"],
            }
        )

    @action(detail=True, methods=["get"])
    def previous_records(self, request, pk=None):
        """Get previous metric records for this player with optional improvement calculation"""
        player_training = self.get_object()

        # Check if a specific metric is requested
        metric_id = request.query_params.get("metric_id")

        if metric_id:
            # Get specific metric record with improvement calculation
            from .services import PlayerTrainingService
            from .utils import calculate_normalized_improvement

            service = PlayerTrainingService()
            metric_record = service.get_previous_record_for_metric(
                player_training, metric_id
            )

            if metric_record:
                # Check if current_value is provided for real-time calculation
                current_value_param = request.GET.get("current_value")

                if current_value_param:
                    # Real-time improvement calculation with input value
                    try:
                        current_value = float(current_value_param)

                        # Calculate improvement using the shared utility function
                        improvement_data = calculate_normalized_improvement(
                            current_value,
                            metric_record["value"],
                            metric_record["is_lower_better"],
                            metric_record.get("normalization_weight", 1.0),
                        )

                        metric_record["improvement"] = improvement_data

                    except (ValueError, TypeError):
                        # Invalid current_value provided
                        metric_record["improvement"] = None
                else:
                    # Check for existing saved record for comparison
                    try:
                        current_record = PlayerMetricRecord.objects.get(
                            player_training=player_training, metric_id=metric_id
                        )

                        # Calculate improvement using the shared utility function
                        improvement_data = calculate_normalized_improvement(
                            current_record.value,
                            metric_record["value"],
                            metric_record["is_lower_better"],
                            metric_record.get("normalization_weight", 1.0),
                        )

                        metric_record["improvement"] = improvement_data

                    except PlayerMetricRecord.DoesNotExist:
                        # No current record to compare against
                        metric_record["improvement"] = None

                return Response({"previous_record": metric_record})
            else:
                return Response(
                    {
                        "previous_record": None,
                        "message": "No previous record found for this metric",
                    }
                )
        else:
            # Get all previous records (existing behavior)
            previous_records = self._get_previous_records(player_training)
            return Response({"previous_records": previous_records})

    @action(detail=False, methods=["post"])
    def bulk_update_attendance(self, request):
        """Update attendance status for multiple player training records"""
        from .services import PlayerTrainingService

        session_id = request.data.get("sessionId")
        player_records = request.data.get("playerRecords", [])

        if not session_id:
            return Response(
                {"detail": "Session ID is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not player_records:
            return Response(
                {"detail": "No player records provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )  # Check session status before updating attendance
        try:
            session = TrainingSession.objects.get(id=session_id)
            if not session.can_manage_attendance():
                return Response(
                    {
                        "detail": f"Attendance cannot be managed for {session.status} sessions. Only ongoing sessions or completed sessions within 24 hours allow attendance management.",
                        "session_status": session.status,
                        "auto_status": session.get_auto_status(),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except TrainingSession.DoesNotExist:
            return Response(
                {"detail": "Training session not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        service = PlayerTrainingService()
        result = service.bulk_update_attendance(session_id, player_records)

        return Response(
            {
                "detail": f"Updated {result['updated_count']} attendance records",
                "updated_count": result["updated_count"],
                "errors": result.get("errors"),
            }
        )

    @action(detail=False, methods=["get"])
    def assigned_metrics(self, request):
        """Get assigned metrics for the current player (session-focused view)"""
        user = request.user

        # Ensure only players can access this endpoint
        if not hasattr(user, "player_profile"):
            raise PermissionDenied("Only players can access assigned metrics")

        player = user.player_profile

        # Get query parameters
        status_filter = request.query_params.get("status")
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")

        # Base queryset for player's training sessions with assigned metrics
        queryset = (
            PlayerTraining.objects.filter(player=player)
            .select_related("session", "session__team")
            .prefetch_related(
                "assigned_metrics",
                "assigned_metrics__category",
                "assigned_metrics__metric_unit",
                "metric_records",
                "metric_records__metric",
            )
            .order_by("-session__date", "-session__start_time")
        )

        # Apply date filters
        if date_from:
            queryset = queryset.filter(session__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(session__date__lte=date_to)
        # Apply status filter
        if status_filter and status_filter != "all":
            if status_filter == "upcoming":
                queryset = queryset.filter(session__status="upcoming")
            elif status_filter == "ongoing":
                queryset = queryset.filter(session__status="ongoing")
            elif status_filter == "completed":
                queryset = queryset.filter(session__status="completed")

        # Serialize and return paginated results
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def assigned_metrics_detail(self, request):
        """Get assigned metrics grouped by training session for the current player"""
        user = request.user

        # Ensure only players can access this endpoint
        if not hasattr(user, "player_profile"):
            raise PermissionDenied("Only players can access assigned metrics")

        player = user.player_profile

        # Get query parameters
        status_filter = request.query_params.get("status")
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        search = request.query_params.get("search")

        # Get PlayerTraining records with assigned metrics
        base_query = PlayerTraining.objects.filter(
            player=player, assigned_metrics__isnull=False
        ).select_related("session", "session__team")

        # Apply date filters
        if date_from:
            base_query = base_query.filter(session__date__gte=date_from)
        if date_to:
            base_query = base_query.filter(session__date__lte=date_to)

        # Get distinct sessions that have assigned metrics for this player
        session_ids = base_query.values_list("session__id", flat=True).distinct()

        # Get the actual PlayerTraining records for these sessions
        player_trainings = (
            PlayerTraining.objects.filter(player=player, session__id__in=session_ids)
            .select_related("session", "session__team")
            .prefetch_related(
                "assigned_metrics",
                "assigned_metrics__category",
                "assigned_metrics__metric_unit",
                "metric_records",
                "metric_records__metric",
            )
            .order_by("-session__date", "-session__start_time")
        )

        # Group by session to avoid duplicates
        sessions_data = []
        total_metrics_count = 0
        status_counts = {"completed": 0, "in_progress": 0, "assigned": 0, "missed": 0}
        sessions_processed = {}  # Track sessions by session ID

        for pt in player_trainings:
            session_id = pt.session.id

            # If we've already processed this session, skip it
            if session_id in sessions_processed:
                continue

            # Get assigned metrics for this session
            assigned_metrics = []
            metric_records_data = []
            for metric in pt.assigned_metrics.all():
                # Get metric record for this session
                metric_record = pt.metric_records.filter(metric=metric).first()

                # Determine individual metric status
                if metric_record and metric_record.value is not None:
                    metric_status = "completed"
                elif pt.session.status == "completed":
                    if pt.attendance_status in ["absent", "excused"]:
                        metric_status = "missed"
                    else:
                        metric_status = "missed"
                elif pt.session.status == "ongoing":
                    metric_status = "in_progress"
                elif pt.session.status == "upcoming":
                    metric_status = "assigned"
                else:
                    metric_status = "assigned"

                # Apply status filter at metric level
                if (
                    status_filter
                    and status_filter != "all"
                    and metric_status != status_filter
                ):
                    continue

                # Count this metric for summary
                total_metrics_count += 1
                status_counts[metric_status] += 1

                # Add to assigned metrics
                assigned_metrics.append(
                    {
                        "id": metric.id,
                        "name": metric.name,
                        "description": metric.description,
                        "metric_unit": (
                            metric.metric_unit.id if metric.metric_unit else None
                        ),
                        "metric_unit_data": (
                            {
                                "id": metric.metric_unit.id,
                                "code": metric.metric_unit.code,
                                "name": metric.metric_unit.name,
                                "normalization_weight": str(
                                    metric.metric_unit.normalization_weight
                                ),
                                "description": metric.metric_unit.description,
                                "is_default": metric.metric_unit.is_default,
                                "created_by": (
                                    metric.metric_unit.created_by.id
                                    if metric.metric_unit.created_by
                                    else None
                                ),
                                "created_by_name": (
                                    f"{metric.metric_unit.created_by.first_name} {metric.metric_unit.created_by.last_name}".strip()
                                    if metric.metric_unit.created_by
                                    else None
                                ),
                            }
                            if metric.metric_unit
                            else None
                        ),
                        "category": metric.category.id if metric.category else None,
                        "category_name": (
                            metric.category.name if metric.category else "General"
                        ),
                        "is_lower_better": metric.is_lower_better,
                        "weight": str(metric.weight),
                    }
                )

                # Add to metric records
                metric_records_data.append(
                    {
                        "id": metric_record.id if metric_record else None,
                        "player_training": pt.id,
                        "metric": metric.id,
                        "metric_name": metric.name,
                        "metric_unit_code": (
                            metric.metric_unit.code if metric.metric_unit else ""
                        ),
                        "metric_unit_name": (
                            metric.metric_unit.name if metric.metric_unit else ""
                        ),
                        "value": (
                            float(metric_record.value)
                            if metric_record and metric_record.value is not None
                            else None
                        ),
                        "player_name": f"{player.user.first_name} {player.user.last_name}".strip(),
                        "notes": metric_record.notes if metric_record else "",
                        "recorded_by": (
                            f"{metric_record.recorded_by.user.first_name} {metric_record.recorded_by.user.last_name}".strip()
                            if metric_record and metric_record.recorded_by
                            else None
                        ),
                        "recorded_at": (
                            metric_record.recorded_at if metric_record else None
                        ),
                        "improvement_from_last": self._calculate_improvement_for_metric(
                            player, metric, metric_record
                        ),
                        "improvement_percentage": self._calculate_improvement_percentage_for_metric(
                            player, metric, metric_record
                        ),
                    }
                )

            # Add search filter for session title
            if search and search.lower() not in pt.session.title.lower():
                continue

            # Only include sessions that have metrics after filtering
            if assigned_metrics:
                session_data = {
                    "id": pt.id,
                    "player": {
                        "id": pt.player.user_id,  # Use user_id since user is the primary key
                        "first_name": pt.player.user.first_name,
                        "last_name": pt.player.user.last_name,
                        "full_name": f"{pt.player.user.first_name} {pt.player.user.last_name}".strip(),
                        "profile": (
                            request.build_absolute_uri(pt.player.user.profile.url)
                            if pt.player.user.profile
                            else None
                        ),
                    },
                    "player_name": f"{pt.player.user.first_name} {pt.player.user.last_name}".strip(),
                    "session": pt.session.id,
                    "session_title": pt.session.title,
                    "session_date": pt.session.date,
                    "session_start_time": pt.session.start_time,
                    "session_end_time": pt.session.end_time,
                    "session_location": pt.session.location,
                    "session_status": pt.session.status,
                    "session_description": pt.session.description,
                    "attendance_status": pt.attendance_status,
                    "notes": pt.notes,
                    "metric_records": metric_records_data,
                    "assigned_metrics": assigned_metrics,
                    "metrics_completion_status": {
                        "total_assigned": len(assigned_metrics),
                        "total_recorded": len(
                            [
                                mr
                                for mr in metric_records_data
                                if mr["value"] is not None
                            ]
                        ),
                        "completion_percentage": (
                            round(
                                (
                                    len(
                                        [
                                            mr
                                            for mr in metric_records_data
                                            if mr["value"] is not None
                                        ]
                                    )
                                    / len(assigned_metrics)
                                    * 100
                                ),
                                1,
                            )
                            if assigned_metrics
                            else 0
                        ),
                        "status": (
                            "completed"
                            if all(
                                mr["value"] is not None for mr in metric_records_data
                            )
                            else (
                                "in_progress"
                                if any(
                                    mr["value"] is not None
                                    for mr in metric_records_data
                                )
                                else "not_started"
                            )
                        ),
                    },
                    "can_record_metrics": pt.session.can_record_metrics(),
                }
                sessions_data.append(session_data)
                sessions_processed[session_id] = True

        # Sort sessions by date (newest first)
        sessions_data.sort(key=lambda x: x["session_date"], reverse=True)

        # Paginate the sessions data
        from django.core.paginator import Paginator

        page_size = int(request.query_params.get("page_size", 10))
        paginator = Paginator(sessions_data, page_size)
        page_number = request.query_params.get("page", 1)
        page_obj = paginator.get_page(page_number)

        return Response(
            {
                "count": paginator.count,
                "next": page_obj.next_page_number() if page_obj.has_next() else None,
                "previous": (
                    page_obj.previous_page_number() if page_obj.has_previous() else None
                ),
                "results": list(page_obj.object_list),
                "summary": {
                    "total_metrics": total_metrics_count,
                    "completed": status_counts["completed"],
                    "in_progress": status_counts["in_progress"],
                    "assigned": status_counts["assigned"],
                    "missed": status_counts["missed"],
                    "completion_rate": (
                        round(
                            (status_counts["completed"] / total_metrics_count * 100), 1
                        )
                        if total_metrics_count > 0
                        else 0
                    ),
                },
            }
        )

    @action(detail=False, methods=["get"])
    def assigned_metrics_overview(self, request):
        """Get overall assigned metrics summary for the current player (no filters applied)"""
        user = request.user

        # Ensure only players can access this endpoint
        if not hasattr(user, "player_profile"):
            raise PermissionDenied("Only players can access assigned metrics")

        player = user.player_profile

        # Get all PlayerTraining records with assigned metrics (no filters)
        player_trainings = (
            PlayerTraining.objects.filter(player=player, assigned_metrics__isnull=False)
            .select_related("session", "session__team")
            .prefetch_related(
                "assigned_metrics", "metric_records", "metric_records__metric"
            )
            .distinct()
        )

        # Calculate overall summary statistics
        total_metrics_count = 0
        status_counts = {"completed": 0, "in_progress": 0, "assigned": 0, "missed": 0}

        # Track processed metrics to avoid duplicates
        processed_metrics = set()

        for pt in player_trainings:
            for metric in pt.assigned_metrics.all():
                # Create unique identifier for metric-session combination
                metric_session_key = f"{metric.id}_{pt.session.id}"
                if metric_session_key in processed_metrics:
                    continue

                processed_metrics.add(metric_session_key)
                total_metrics_count += 1

                # Get metric record for this session
                metric_record = pt.metric_records.filter(metric=metric).first()

                # Determine individual metric status
                if metric_record and metric_record.value is not None:
                    metric_status = "completed"
                elif pt.session.status == "completed":
                    if pt.attendance_status in ["absent", "excused"]:
                        metric_status = "missed"
                    else:
                        metric_status = "missed"
                elif pt.session.status == "ongoing":
                    metric_status = "in_progress"
                elif pt.session.status == "upcoming":
                    metric_status = "assigned"
                else:
                    metric_status = "assigned"

                status_counts[metric_status] += 1

        return Response(
            {
                "total_metrics": total_metrics_count,
                "completed": status_counts["completed"],
                "in_progress": status_counts["in_progress"],
                "assigned": status_counts["assigned"],
                "missed": status_counts["missed"],
                "completion_rate": (
                    round((status_counts["completed"] / total_metrics_count * 100), 1)
                    if total_metrics_count > 0
                    else 0
                ),
            }
        )

    @action(detail=False, methods=["get"])
    def training_overview(self, request):
        """Get training overview statistics for the current player"""
        user = request.user

        # Ensure only players can access this endpoint
        if not hasattr(user, "player_profile"):
            raise PermissionDenied("Only players can access training overview")

        player = user.player_profile

        # Calculate date range for 90 days span (only for recent improvement)
        from datetime import datetime, timedelta

        ninety_days_ago = timezone.now().date() - timedelta(days=90)

        # Get all training sessions for this player (all time)
        all_trainings = PlayerTraining.objects.filter(player=player)

        # 1. Total number of training sessions (all time)
        total_sessions = all_trainings.count()

        # 2. Present attendance percentage (all time)
        present_count = all_trainings.filter(
            attendance_status__in=["present", "late"]
        ).count()

        attendance_percentage = (
            round((present_count / total_sessions * 100), 1)
            if total_sessions > 0
            else 0
        )

        # 3. Number of times late status (all time)
        late_count = all_trainings.filter(attendance_status="late").count()

        # 4. Number of training sessions attended (present or late)
        attended_count = present_count

        # 5. Recent improvement using same method as dashboard (90 days span only)
        # Use ProgressService to ensure consistency with dashboard
        from .services.progress_service import ProgressService

        recent_improvement_data = ProgressService.calculate_recent_improvement(
            player, date_from=ninety_days_ago, date_to=timezone.now().date()
        )

        if recent_improvement_data:
            average_improvement = round(recent_improvement_data["percentage"], 1)
            metrics_analyzed = recent_improvement_data["metric_count"]
        else:
            average_improvement = 0
            metrics_analyzed = 0

        return Response(
            {
                "total_sessions": total_sessions,
                "attendance_percentage": attendance_percentage,
                "late_count": late_count,
                "attended_count": attended_count,  # renamed from absent_count
                "recent_improvement": average_improvement,
                "metrics_analyzed": metrics_analyzed,
                "improvement_date_range_days": 90,
            }
        )

    def _calculate_improvement_for_metric(self, player, metric, current_record):
        """Calculate improvement from last metric record for a specific metric"""
        if not current_record or current_record.value is None:
            return None

        # Get the previous record for this metric for this player
        previous_record = (
            PlayerMetricRecord.objects.filter(
                player_training__player=player,
                metric=metric,
                value__isnull=False,
                player_training__session__date__lt=current_record.player_training.session.date,
            )
            .order_by(
                "-player_training__session__date",
                "-player_training__session__start_time",
            )
            .first()
        )

        if not previous_record:
            return None

        # Use the shared calculation function with normalization weights
        from .utils import calculate_normalized_improvement

        # Get normalization weight from metric unit
        normalization_weight = 1.0
        if metric.metric_unit:
            normalization_weight = float(metric.metric_unit.normalization_weight)

        improvement_data = calculate_normalized_improvement(
            float(current_record.value),
            float(previous_record.value),
            metric.is_lower_better,
            normalization_weight,
        )

        return improvement_data["raw_value"]

    def _calculate_improvement_percentage_for_metric(
        self, player, metric, current_record
    ):
        """Calculate improvement percentage from last metric record for a specific metric"""
        if not current_record or current_record.value is None:
            return None

        # Get the previous record for this metric for this player
        previous_record = (
            PlayerMetricRecord.objects.filter(
                player_training__player=player,
                metric=metric,
                value__isnull=False,
                player_training__session__date__lt=current_record.player_training.session.date,
            )
            .order_by(
                "-player_training__session__date",
                "-player_training__session__start_time",
            )
            .first()
        )

        if not previous_record:
            return None

        # Use the shared calculation function with normalization weights
        from .utils import calculate_normalized_improvement

        # Get normalization weight from metric unit
        normalization_weight = 1.0
        if metric.metric_unit:
            normalization_weight = float(metric.metric_unit.normalization_weight)

        improvement_data = calculate_normalized_improvement(
            float(current_record.value),
            float(previous_record.value),
            metric.is_lower_better,
            normalization_weight,
        )

        return improvement_data["percentage"]


class PlayerMetricRecordViewSet(viewsets.ModelViewSet):
    queryset = PlayerMetricRecord.objects.all().select_related(
        "player_training__player", "player_training__session", "metric"
    )
    serializer_class = PlayerMetricRecordSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["player_training__player", "metric", "player_training__session"]

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
            "player_training__player", "player_training__session", "metric"
        )

        # For admins, show all player metric records
        if user.is_admin:
            return base_queryset

        # For coaches, show only metric records for their team's players
        if hasattr(user, "coach_profile"):
            coach_teams = get_coach_teams(user.coach_profile)
            return base_queryset.filter(player_training__session__team__in=coach_teams)

        # For players, show only their own metric records
        if hasattr(user, "player_profile"):
            return base_queryset.filter(player_training__player=user.player_profile)

        # User doesn't have appropriate role - deny access
        raise PermissionDenied(
            "You don't have permission to access player metric records"
        )

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        - GET requests are accessible to authenticated users (filtered by get_queryset)
        - POST/CREATE requests are restricted to admin or coach users
        - PUT/PATCH/DELETE requests can be done by admins or coaches (with team restrictions)
        """
        if self.action in ["create", "update", "partial_update", "destroy"]:
            permission_classes = [IsAdminOrCoachUser]
        else:
            permission_classes = [IsAuthenticated]

        return [permission() for permission in permission_classes]

    def perform_create(self, serializer):
        """Validate session status before creating metric records"""
        player_training = serializer.validated_data.get("player_training")
        session = player_training.session

        # Check if metrics can be recorded for this session
        if not session.can_record_metrics():
            raise ValidationError(
                {
                    "detail": f"Metrics cannot be recorded for {session.status} sessions. Only ongoing and completed sessions allow metrics recording.",
                    "session_status": session.status,
                    "auto_status": session.get_auto_status(),
                }
            )

        # Validate team permissions for coaches
        if self.request.user.is_admin:
            # Admins can create metric records for any team
            serializer.save(
                recorded_by_id=getattr(self.request.user, "coach_profile_id", None)
            )
        elif self.request.user.is_coach and hasattr(self.request.user, "coach_profile"):
            # Coaches can only create metric records for their team's players
            coach_teams = get_coach_teams(self.request.user.coach_profile)

            # Check if the metric record belongs to one of the coach's teams
            if session.team and session.team in coach_teams:
                serializer.save(recorded_by=self.request.user.coach_profile)
            else:
                raise PermissionDenied(
                    "You can only create metric records for your own team's players"
                )
        else:
            raise PermissionDenied("You don't have permission to create metric records")

    def perform_update(self, serializer):
        """Only allow coaches to update metric records for their own team's players"""
        if self.request.user.is_admin:
            # Admins can update any metric record
            serializer.save()
        elif self.request.user.is_coach and hasattr(self.request.user, "coach_profile"):
            # Coaches can only update metric records for their team's players
            coach_teams = get_coach_teams(self.request.user.coach_profile)
            metric_record = serializer.instance

            # Check if the metric record belongs to one of the coach's teams
            if (
                metric_record.player_training.session.team
                and metric_record.player_training.session.team in coach_teams
            ):
                serializer.save()
            else:
                raise PermissionDenied(
                    "You can only update metric records for your own team's players"
                )
        else:
            raise PermissionDenied("You don't have permission to update metric records")

    def perform_destroy(self, instance):
        """Only allow coaches to delete metric records for their own team's players"""
        if self.request.user.is_admin:
            # Admins can delete any metric record
            instance.delete()
        elif self.request.user.is_coach and hasattr(self.request.user, "coach_profile"):
            # Coaches can only delete metric records for their team's players
            coach_teams = get_coach_teams(self.request.user.coach_profile)

            # Check if the metric record belongs to one of the coach's teams
            if (
                instance.player_training.session.team
                and instance.player_training.session.team in coach_teams
            ):
                instance.delete()
            else:
                raise PermissionDenied(
                    "You can only delete metric records for your own team's players"
                )
        else:
            raise PermissionDenied("You don't have permission to delete metric records")


class PlayerProgressViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Player.objects.all()
    serializer_class = PlayerProgressSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["team"]

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
        if hasattr(user, "coach_profile"):
            coach_teams = get_coach_teams(user.coach_profile)
            return base_queryset.filter(
                team__in=coach_teams
            )  # For players, show only their own data
        if hasattr(user, "player_profile"):
            return base_queryset.filter(user_id=user.id)

        # User doesn't have appropriate role - deny access
        raise PermissionDenied(
            "You don't have permission to access player progress data"
        )

    @action(detail=False, methods=["get"])
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

    @action(detail=False, methods=["get"])
    def player_radar_chart(self, request):
        """Get radar chart data for a player's performance across training categories"""
        from django.db.models import Avg, Max, Min, Count
        from decimal import Decimal
        from django.utils.dateparse import parse_date

        player_id = request.query_params.get("player_id")
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")

        if not player_id:
            return Response(
                {"detail": "player_id parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            player = Player.objects.get(user_id=player_id)
        except Player.DoesNotExist:
            return Response(
                {"detail": "Player not found"}, status=status.HTTP_404_NOT_FOUND
            )

        # Apply role-based access control
        user = request.user
        if not user.is_admin:  # For coaches, check if player is in their teams
            if hasattr(user, "coach_profile"):
                from django.db.models import Q
                from teams.models import Team

                coach_teams = Team.objects.filter(
                    Q(head_coach=user.coach_profile)
                    | Q(assistant_coach=user.coach_profile)
                )
                if player.team not in coach_teams:
                    raise PermissionDenied(
                        "You can only access radar chart data for players in your teams"
                    )
            # For players, check if they're accessing their own data
            elif hasattr(user, "player_profile"):
                if player != user.player_profile:
                    raise PermissionDenied(
                        "You can only access your own radar chart data"
                    )
            else:
                raise PermissionDenied(
                    "You don't have permission to access radar chart data"
                )
        # Build base query for player's metric records
        records_query = PlayerMetricRecord.objects.filter(
            player_training__player=player,
            value__isnull=False,  # Only include records with actual values
        ).select_related(
            "metric__category", "metric__metric_unit", "player_training__session"
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
                    status=status.HTTP_400_BAD_REQUEST,
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
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Get all training categories with metrics for this player
        categories_with_data = []
        categories = TrainingCategory.objects.filter(
            metrics__records__player_training__player=player
        ).distinct()


        for category in categories:
            # Get all records for metrics in this category
            category_records = records_query.filter(metric__category=category).order_by(
                "player_training__session__date"
            )

            if not category_records.exists():
                continue

            # Calculate performance metrics for this category
            category_metrics = []
            metrics_in_category = TrainingMetric.objects.filter(
                category=category, records__player_training__player=player
            ).distinct()

            total_improvement = 0
            metrics_with_improvement = 0
            latest_performance_score = 0

            for metric in metrics_in_category:
                metric_records = category_records.filter(metric=metric)

                if metric_records.count() < 1:
                    continue
                
                # Get first and latest records for improvement calculation
                # Use all metric records (not date-filtered) to get true first/latest
                all_metric_records = PlayerMetricRecord.objects.filter(
                    player_training__player=player,
                    metric=metric,
                    value__isnull=False
                ).order_by("player_training__session__date", "player_training__session__start_time")
                
                if all_metric_records.count() < 1:
                    continue
                    
                latest_record = all_metric_records.last()
                
                # Check for null values
                if latest_record.value is None:
                    continue

                latest_value = float(latest_record.value)
                improvement = 0
                performance_score = 50  # Default neutral score
                
                # Calculate improvement if we have multiple records
                if all_metric_records.count() >= 2:
                    first_record = all_metric_records.first()
                    if first_record.value is not None:
                        first_value = float(first_record.value)
                        
                        # Calculate improvement percentage
                        if first_value != 0:
                            raw_improvement = ((latest_value - first_value) / first_value) * 100

                            # Apply normalization and direction logic
                            normalization_weight = 1.0
                            if metric.metric_unit:
                                normalization_weight = float(
                                    metric.metric_unit.normalization_weight
                                )

                            improvement = raw_improvement * normalization_weight

                            # For metrics where lower is better, invert the improvement
                            if metric.is_lower_better:
                                improvement = -improvement

                            # Cap extreme improvements to prevent skewing
                            improvement = max(-500, min(500, improvement))

                            # Calculate performance score based on improvement
                            if improvement >= 0:
                                # Positive improvement: scale from 50 to 100
                                improvement_factor = min(improvement / 50, 2.0)
                                performance_score = 50 + (
                                    50 * improvement_factor / (1 + improvement_factor)
                                )
                            else:
                                # Negative improvement: scale from 50 to 0
                                improvement_factor = min(abs(improvement) / 50, 2.0)
                                performance_score = 50 - (
                                    50 * improvement_factor / (1 + improvement_factor)
                                )
                        else:
                            # Handle zero baseline case
                            # For zero baseline, use absolute value scoring
                            if metric.is_lower_better:
                                # For lower-is-better: any positive value is worse
                                if latest_value > 0:
                                    performance_score = max(20, 50 - min(latest_value * 10, 30))
                                else:
                                    performance_score = 80  # Zero or negative is good
                            else:
                                # For higher-is-better: positive values are better
                                performance_score = min(80, 50 + min(latest_value * 10, 30))
                            
                            improvement = 0  # Can't calculate meaningful improvement from zero
                else:
                    # Single record - use absolute scoring relative to typical ranges
                    if metric.is_lower_better:
                        # For lower-is-better: score inversely with latest value
                        performance_score = max(30, min(70, 60 - (latest_value * 2)))
                    else:
                        # For higher-is-better: score directly with latest value
                        performance_score = max(30, min(70, 40 + (latest_value * 2)))
                    
                    improvement = 0  # No improvement can be calculated

                # Ensure score stays within reasonable bounds
                performance_score = max(0, min(100, performance_score))
                
                # Add to totals
                total_improvement += improvement
                latest_performance_score += performance_score
                metrics_with_improvement += 1

                category_metrics.append(
                    {
                        "metric_name": metric.name,
                        "metric_unit": (
                            metric.metric_unit.code if metric.metric_unit else ""
                        ),
                        "latest_value": float(latest_record.value),
                        "improvement_percentage": round(improvement, 2),
                        "performance_score": round(performance_score, 2),
                        "records_count": all_metric_records.count(),
                        "has_improvement_data": all_metric_records.count() >= 2,
                    }
                )

            # Calculate category averages with validation
            if metrics_with_improvement > 0:
                avg_improvement = total_improvement / metrics_with_improvement
                avg_performance_score = latest_performance_score / metrics_with_improvement
            else:
                avg_improvement = 0
                avg_performance_score = 50  # Neutral score when no data

            # Only include categories that have valid metrics
            if metrics_with_improvement > 0:
                categories_with_data.append(
                    {
                        "category_id": category.id,
                        "category_name": category.name,
                        "description": category.description,
                        "average_improvement": round(avg_improvement, 2),
                        "performance_score": round(avg_performance_score, 2),
                        "metrics_count": metrics_with_improvement,
                        "total_records": category_records.count(),
                        "metrics_data": category_metrics,
                    }
                )

        # Prepare radar chart data
        chart_data = {
            "player_id": player_id,
            "player_name": f"{player.user.first_name} {player.user.last_name}",
            "categories": categories_with_data,
            "chart_labels": [cat["category_name"] for cat in categories_with_data],
            "performance_scores": [
                cat["performance_score"] for cat in categories_with_data
            ],
            "improvement_percentages": [
                cat["average_improvement"] for cat in categories_with_data
            ],
            "date_range": {"from": date_from, "to": date_to},
            "summary": {
                "categories_tracked": len(categories_with_data),
                "total_metrics": sum(
                    cat["metrics_count"] for cat in categories_with_data
                ),
                "overall_performance": (
                    round(
                        sum(cat["performance_score"] for cat in categories_with_data)
                        / len(categories_with_data),
                        2,
                    )
                    if categories_with_data
                    else 0
                ),
                "overall_improvement": (
                    round(
                        sum(cat["average_improvement"] for cat in categories_with_data)
                        / len(categories_with_data),
                        2,
                    )
                    if categories_with_data
                    else 0
                ),
            },
        }

        return Response(chart_data)

    @action(detail=False, methods=["get"])
    def multi_player_overview(self, request):
        """
        Get team overview statistics with weighted improvements for multiple players.

        Expects GET parameters:
        - team: team_slug (required if player_ids not provided)
        - metric_id: metric_id (required)
        - player_ids: comma-separated list of player IDs (optional, for filtering specific players within a team)

        Date range is automatically set to 3 months from now for recent improvement calculations.

        Returns:
        - number_of_players: Total players analyzed
        - recent_team_improvement: Team average improvement over last 3 months (weighted)
        - overall_team_improvement: Team average improvement from first to latest records (weighted)
        - best_player: Player with highest weighted improvement
        - team_summary: Additional team statistics
        """
        from .services import TeamOverviewService

        # Get parameters
        team_slug = request.query_params.get("team")
        metric_id = request.query_params.get("metric_id")
        player_ids_param = request.query_params.get("player_ids", "")

        try:
            # Use service to get team overview
            service = TeamOverviewService()
            response_data = service.get_team_overview(
                team_slug=team_slug,
                metric_id=metric_id,
                player_ids_param=player_ids_param,
                user=request.user,
            )

            return Response(response_data)

        except ValueError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except PermissionError as e:
            raise PermissionDenied(str(e))
        except Exception as e:
            return Response(
                {"detail": f"An error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


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
        if hasattr(user, "coach_profile"):
            coach_teams = get_coach_teams(user.coach_profile)
            return base_queryset.filter(session__team__in=coach_teams)

        # For players, show only their own attendance records
        if hasattr(user, "player_profile"):
            return base_queryset.filter(player=user.player_profile)

        # User doesn't have appropriate role - deny access
        raise PermissionDenied(
            "You don't have permission to access attendance analytics"
        )

    @action(detail=False, methods=["get"])
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
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["get"])
    def trends(self, request):
        """Get training sessions per month trends"""
        try:
            base_queryset = self.get_base_queryset(request)
            filters = self._get_filters(request)
            
            # Get period parameter from request (default to monthly)
            period = request.query_params.get('period', 'monthly')

            # Use service to calculate session trends with specified period
            trends_data = AttendanceAnalyticsService.calculate_attendance_trends(
                base_queryset, filters, period
            )

            return Response(trends_data)

        except Exception as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["get"])
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
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["get"])
    def players(self, request):
        """Get individual player attendance analytics"""
        try:
            base_queryset = self.get_base_queryset(request)
            filters = self._get_filters(
                request
            )  # Use service to calculate player analytics
            players_data = (
                AttendanceAnalyticsService.calculate_player_attendance_analytics(
                    base_queryset, filters, request
                )
            )

            return Response(players_data)

        except Exception as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["get"])
    def player_detail(self, request):
        """Get detailed attendance analytics for a specific player"""
        try:
            player_id = request.query_params.get("player_id")
            if not player_id:
                return Response(
                    {"error": "player_id parameter is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            base_queryset = self.get_base_queryset(request)
            filters = self._get_filters(request)
            user = request.user  # Use service to get player detail analytics
            data = AttendanceAnalyticsService.get_player_detail_analytics(
                player_id, base_queryset, filters, user, request
            )

            return Response(data)

        except Exception as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _get_filters(self, request):
        """
        Extract filters from request parameters
        Note: Role-based filtering is handled separately in get_base_queryset()
        """
        return AttendanceAnalyticsService.get_filters(request)

    @action(detail=True, methods=["post"])
    def assign_metrics_to_players(self, request, pk=None):
        """Assign specific metrics to specific players in a training session"""
        from .services import TrainingSessionService

        session = self.get_object()

        # Check if metrics can be configured for this session
        if not session.can_configure_metrics():
            return Response(
                {
                    "detail": f"Metrics cannot be configured for {session.status} sessions. Only upcoming and ongoing sessions allow metrics configuration.",
                    "session_status": session.status,
                    "auto_status": session.get_auto_status(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        player_ids = request.data.get("player_ids", [])
        metric_ids = request.data.get("metric_ids", [])
        if not isinstance(player_ids, list) or not isinstance(metric_ids, list):
            return Response(
                {"detail": "player_ids and metric_ids must be provided as lists"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not player_ids:
            return Response(
                {"detail": "player_ids must be a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        service = TrainingSessionService()
        result = service.assign_metrics_to_players_in_session(
            session, player_ids, metric_ids
        )

        # Calculate totals from the results
        total_added = sum(
            player_result.get("created_records", 0)
            for player_result in result.get("results", [])
        )
        total_removed = sum(
            player_result.get("deleted_records", 0)
            for player_result in result.get("results", [])
        )
        players_processed = result.get("total_players_processed", 0)
        return Response(
            {
                "detail": f"Processed {players_processed} players - {total_added} metrics added, {total_removed} metrics removed",
                "total_players_processed": players_processed,
                "total_metrics_added": total_added,
                "total_metrics_removed": total_removed,
                "player_count": len(player_ids),
                "metric_count": len(metric_ids),
                "success": result.get("success", True),
                "results": result.get("results", []),
            }
        )

    @action(detail=False, methods=["get"], url_path="team-insights/(?P<team_id>[^/.]+)")
    def team_progress_insights(self, request, team_id=None):
        """Get AI-powered team progress insights for recent training sessions"""
        from .services.training_completion_service import TrainingCompletionService
        from teams.models import Team

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return Response(
                {"detail": "Team not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if user has permission to view this team's insights
        user = request.user
        if not (
            user.is_admin
            or (
                hasattr(user, "coach_profile")
                and team in get_coach_teams(user.coach_profile)
            )
            or (hasattr(user, "player_profile") and user.player_profile.team == team)
        ):
            return Response(
                {"detail": "You don't have permission to view this team's insights."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Get the number of sessions to analyze (optional query parameter)
        sessions_limit = int(request.query_params.get("sessions_limit", 5))
        sessions_limit = max(1, min(sessions_limit, 10))  # Limit between 1 and 10

        # Generate team insights
        team_insights = TrainingCompletionService.generate_team_progress_insights(
            team, sessions_limit=sessions_limit
        )

        return Response(
            {
                "team_insights": team_insights,
                "team_id": team.id,
                "team_name": team.name,
                "sessions_analyzed": sessions_limit,
            }
        )

    @action(detail=False, methods=["get"])
    def attendance_tracker(self, request):
        """
        Track attendance for all teams or a specific team over a date range.
        Role-based access control:
        - Admin: Can view all teams
        - Coach: Can only view their assigned teams (if coach has only 1 team, automatically shows detailed view)
        - Player: Can only view their own team
        
        Params:
        - team: team_id or slug (optional)
        - start_date: YYYY-MM-DD (optional, defaults to 7 days ago)
        - end_date: YYYY-MM-DD (optional, defaults to today)
        Returns:
        - For each team (or the specified team), for each day in the date range:
            - If a session exists: number of present, total players, percentage
            - If no session: null for that day
        - When a specific team is requested OR when coach has only 1 team, also includes individual player attendance:
            - For each player: attendance status for each day in the range
            - Player details: id, name, jersey_number
        """
        from datetime import datetime, timedelta
        from teams.models import Team
        from django.utils import timezone

        # Check if user has appropriate role
        user = request.user
        if not (user.is_admin or hasattr(user, "coach_profile") or hasattr(user, "player_profile")):
            return Response(
                {"error": "You don't have permission to access attendance tracking data."},
                status=status.HTTP_403_FORBIDDEN,
            )

        date_from = request.query_params.get("start_date")
        date_to = request.query_params.get("end_date")
        # Default to last 7 days if not provided
        if not date_from or not date_to:
            today = timezone.now().date()
            one_week_ago = today - timedelta(days=6)
            date_from = one_week_ago.strftime("%Y-%m-%d")
            date_to = today.strftime("%Y-%m-%d")
        team_param = request.query_params.get("team")
        # No error if missing, defaults above
        try:
            start_date = datetime.strptime(date_from, "%Y-%m-%d").date()
            end_date = datetime.strptime(date_to, "%Y-%m-%d").date()
        except Exception:
            return Response(
                {"error": "Invalid date format. Use YYYY-MM-DD."}, status=400
            )
        days = (end_date - start_date).days + 1
        date_list = [start_date + timedelta(days=i) for i in range(days)]

        # Get teams based on user role
        user = request.user
        
        if team_param:
            # Get the specific team requested
            teams = (
                Team.objects.filter(id=team_param)
                if team_param.isdigit()
                else Team.objects.filter(slug=team_param)
            )
            
            # Apply role-based access control for the specific team
            if not user.is_admin:
                if hasattr(user, "coach_profile"):
                    coach_teams = get_coach_teams(user.coach_profile)
                    teams = teams.filter(id__in=[team.id for team in coach_teams])
                elif hasattr(user, "player_profile"):
                    # Players can only see their own team
                    teams = teams.filter(id=user.player_profile.team.id)
                else:
                    teams = Team.objects.none()  # No access for other roles
        else:
            # Get all teams based on user role
            if user.is_admin:
                teams = Team.objects.all()
            elif hasattr(user, "coach_profile"):
                teams = get_coach_teams(user.coach_profile)
            elif hasattr(user, "player_profile"):
                # Players can only see their own team
                teams = Team.objects.filter(id=user.player_profile.team.id)
            else:
                teams = Team.objects.none()  # No access for other roles

        # Check if user has access to any teams or if the specific team was found
        if not teams.exists():
            if team_param:
                return Response(
                    {"error": "Team not found or you don't have permission to access this team's attendance data."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            else:
                return Response(
                    {"error": "You don't have access to any team's attendance data."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # Special case: If coach has only 1 team and no team_param is specified, show detailed view
        show_detailed_view = team_param is not None
        if not team_param and hasattr(user, "coach_profile") and teams.count() == 1:
            show_detailed_view = True

        result = []
        for team in teams:
            attendance = {}
            players_data = []

            # If specific team is requested OR coach has only 1 team, include detailed player data
            if show_detailed_view:
                # Get dates that have sessions for this team within the date range
                session_dates = (
                    TrainingSession.objects.filter(
                        team=team, date__gte=start_date, date__lte=end_date
                    )
                    .values_list("date", flat=True)
                    .distinct()
                )

                # Use only dates that have sessions
                dates_to_process = sorted(session_dates)

                # Get all players from this team
                team_players = Player.objects.filter(team=team).select_related("user")

                for player in team_players:
                    player_attendance = {}
                    for day in dates_to_process:
                        session = TrainingSession.objects.filter(
                            team=team, date=day
                        ).first()
                        if session:
                            player_training = PlayerTraining.objects.filter(
                                session=session, player=player
                            ).first()

                            if player_training:
                                player_attendance[str(day)] = {
                                    "status": player_training.attendance_status,
                                    "has_session": True,
                                }
                            else:
                                # Player not enrolled in this session
                                player_attendance[str(day)] = {
                                    "status": "not_enrolled",
                                    "has_session": True,
                                }

                    profile_url = (
                        request.build_absolute_uri(player.user.profile.url)
                        if player.user.profile
                        else None
                    )
                    players_data.append(
                        {
                            "id": player.user_id,  # Use user_id since it's the primary key
                            "name": f"{player.user.first_name} {player.user.last_name}",
                            "profile": profile_url,
                            "jersey_number": getattr(player, "jersey_number", None),
                            "attendance": player_attendance,
                        }
                    )

                # Calculate team-level attendance for session dates only
                for day in dates_to_process:
                    session = TrainingSession.objects.filter(
                        team=team, date=day
                    ).first()
                    if session:
                        total_players = PlayerTraining.objects.filter(
                            session=session
                        ).count()
                        present_count = PlayerTraining.objects.filter(
                            session=session, attendance_status__in=["present", "late"]
                        ).count()
                        percentage = (
                            round((present_count / total_players * 100), 1)
                            if total_players > 0
                            else 0
                        )
                        attendance[str(day)] = {
                            "present": present_count,
                            "total": total_players,
                            "percentage": percentage,
                            "has_session": True,
                        }
            else:
                # For all teams view, use all dates in range
                for day in date_list:
                    sessions = TrainingSession.objects.filter(team=team, date=day)
                    if sessions.exists():
                        session = sessions.first()
                        total_players = PlayerTraining.objects.filter(
                            session=session
                        ).count()
                        present_count = PlayerTraining.objects.filter(
                            session=session, attendance_status__in=["present", "late"]
                        ).count()
                        percentage = (
                            round((present_count / total_players * 100), 1)
                            if total_players > 0
                            else 0
                        )
                        attendance[str(day)] = {
                            "present": present_count,
                            "total": total_players,
                            "percentage": percentage,
                            "has_session": True,
                        }
                    else:
                        attendance[str(day)] = None

            logo_url = request.build_absolute_uri(team.logo.url) if team.logo else None
            team_data = {
                "team": team.name,
                "team_id": team.id,
                "logo": logo_url,
                "attendance": attendance,
            }

            # Add players data if specific team is requested OR coach has only 1 team
            if show_detailed_view:
                team_data["players"] = players_data

            result.append(team_data)
        return Response(result)
