"""
Team Analytics Views

Separate views for team analytics functionality using the refactored services.
This module provides endpoints for team health metrics, training effectiveness,
and performance summaries.
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.exceptions import PermissionDenied
from datetime import timedelta

from .services.attendance_analytics_service import (
    AttendanceAnalyticsService, 
    TeamAnalyticsService, 
    TrainingEfficiencyService
)
from .models import TrainingSession
from teams.models import Team


class TeamAnalyticsViewSet(viewsets.ViewSet):
    """
    ViewSet for team analytics endpoints that use the refactored services
    """
    permission_classes = [IsAuthenticated]
    
    def get_team_queryset(self, team_slug):
        """Get training sessions for a specific team with role-based filtering"""
        from django.db.models import Q
        from teams.models import Team
        
        user = self.request.user
        
        try:
            team = Team.objects.get(slug=team_slug)
        except Team.DoesNotExist:
            raise PermissionDenied("Team not found")
        
        # Role-based access control
        if user.is_admin:
            # Admin can access all teams
            pass
        elif hasattr(user, 'coach_profile'):
            # Coach can only access their teams
            coach_teams = Team.objects.filter(
                Q(head_coach=user.coach_profile) | Q(assistant_coach=user.coach_profile)
            )
            if team not in coach_teams:
                raise PermissionDenied("You can only access analytics for your own teams")
        elif hasattr(user, 'player_profile'):
            # Player can only access their team
            if user.player_profile.team != team:
                raise PermissionDenied("You can only access analytics for your own team")
        else:
            raise PermissionDenied("You don't have permission to access team analytics")
        
        return TrainingSession.objects.filter(team=team)
    
    @action(detail=False, methods=['get'])
    def health_metrics(self, request):
        """Get comprehensive team health metrics"""
        try:
            team_slug = request.query_params.get('team_id')
            if not team_slug:
                return Response(
                    {'error': 'team_id parameter is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
              # Get base queryset with role-based filtering
            self.get_team_queryset(team_slug)  # This validates permissions
            
            # Get attendance data using the attendance service
            base_queryset = AttendanceAnalyticsService.get_base_queryset(request.user)
            filters = AttendanceAnalyticsService.get_filters(request)
            filters['session__team__slug'] = team_slug
            
            # Get attendance analytics
            attendance_data = AttendanceAnalyticsService.calculate_attendance_overview(
                base_queryset, filters
            )
              # Get training sessions for additional context
            training_sessions = self.get_team_queryset(team_slug)
            
            # No need to calculate comprehensive team overview metrics anymore
            # This data is now displayed as upcoming games and training sessions in the frontend
            
            return Response({
                'team_slug': team_slug,
                'attendance_data': attendance_data,
                'timestamp': request.query_params.get('timestamp')
            })
            
        except PermissionDenied as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_403_FORBIDDEN
            )
        except Exception as e:
            return Response(
                {'error': f'Failed to calculate health metrics: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def training_effectiveness(self, request):
        """Get training effectiveness metrics"""
        try:
            team_slug = request.query_params.get('team_id')
            if not team_slug:
                return Response(
                    {'error': 'team_id parameter is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
              # Get base queryset with role-based filtering
            training_sessions = self.get_team_queryset(team_slug)
            
            # Get attendance data using the attendance service
            base_queryset = AttendanceAnalyticsService.get_base_queryset(request.user)
            filters = AttendanceAnalyticsService.get_filters(request)
            filters['session__team__slug'] = team_slug
            
            attendance_data = AttendanceAnalyticsService.calculate_attendance_overview(
                base_queryset, filters
            )
            
            # Calculate training effectiveness using the service
            effectiveness_score = TrainingEfficiencyService.calculate_training_effectiveness_score(
                team_slug, training_sessions, attendance_data
            )
            
            return Response({
                'team_slug': team_slug,
                'effectiveness_score': effectiveness_score,
                'attendance_rate': attendance_data.get('overall_attendance_rate', 0),
                'total_sessions': attendance_data.get('total_sessions', 0),
                'timestamp': request.query_params.get('timestamp')
            })
            
        except PermissionDenied as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_403_FORBIDDEN
            )
        except Exception as e:
            return Response(
                {'error': f'Failed to calculate training effectiveness: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def weekly_aggregation(self, request):
        """Get weekly training aggregation data"""
        try:
            team_slug = request.query_params.get('team_id')
            if not team_slug:
                return Response(
                    {'error': 'team_id parameter is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
              # Get base queryset with role-based filtering
            training_sessions = self.get_team_queryset(team_slug)
            
            # Get attendance trends for weekly aggregation
            base_queryset = AttendanceAnalyticsService.get_base_queryset(request.user)
            filters = AttendanceAnalyticsService.get_filters(request)
            filters['session__team__slug'] = team_slug
            
            attendance_trends = AttendanceAnalyticsService.calculate_attendance_trends(
                base_queryset, filters, period='weekly'
            )
            
            # Convert training sessions to data format expected by service
            training_data = []
            for session in training_sessions:
                training_data.append({
                    'date': session.date.isoformat(),
                    'players_count': session.players.count(),
                    'duration_minutes': session.duration_minutes or 120
                })
            
            # Process weekly aggregation using the service
            weekly_data = TrainingEfficiencyService.process_weekly_training_aggregation(
                training_data, attendance_trends
            )
            
            return Response({
                'team_slug': team_slug,
                'weekly_aggregation': weekly_data,
                'attendance_trends': attendance_trends,
                'timestamp': request.query_params.get('timestamp')
            })
            
        except PermissionDenied as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_403_FORBIDDEN
            )
        except Exception as e:
            return Response(
                {'error': f'Failed to process weekly aggregation: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def performance_summary(self, request):
        """Get comprehensive performance summary combining all metrics"""
        try:
            team_slug = request.query_params.get('team_id')
            if not team_slug:
                return Response(
                    {'error': 'team_id parameter is required'},                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get base data
            training_sessions = self.get_team_queryset(team_slug)
            base_queryset = AttendanceAnalyticsService.get_base_queryset(request.user)
            filters = AttendanceAnalyticsService.get_filters(request)
            filters['session__team__slug'] = team_slug
            
            # Get all analytics data
            attendance_data = AttendanceAnalyticsService.calculate_attendance_overview(
                base_queryset, filters            )
            
            # Team overview metrics calculation removed (replaced by upcoming events in frontend)
            
            # Calculate training effectiveness score
            effectiveness_score = TrainingEfficiencyService.calculate_training_effectiveness_score(
                team_slug, training_sessions, attendance_data
            )
            
            return Response({
                'team_slug': team_slug,
                'summary': {
                    'training_effectiveness': effectiveness_score,
                    'attendance_overview': attendance_data,
                    'overall_performance_score': 0  # Removed metric calculation
                },
                'timestamp': request.query_params.get('timestamp')
            })
            
        except PermissionDenied as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_403_FORBIDDEN
            )
        except Exception as e:
            return Response(
                {'error': f'Failed to generate performance summary: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
