"""
Attendance Analytics Service

This service extracts and refactors attendance analytics logic from views
to make it reusable across different parts of the application.
"""

from django.db.models import Count, Q, F, Avg
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from datetime import datetime, timedelta
from ..models import PlayerTraining, TrainingSession
from users.models import User


class AttendanceAnalyticsService:
    """Service class for attendance analytics calculations"""

    @staticmethod
    def get_base_queryset(user=None):
        """
        Get base queryset for attendance data with role-based filtering
        
        Args:
            user: User instance for role-based filtering
            
        Returns:
            QuerySet: Filtered PlayerTraining queryset
        """
        if not user:
            return PlayerTraining.objects.all()
        
        queryset = PlayerTraining.objects.all()
        
        if user.is_admin:            # Admins can see all training records
            return queryset
        elif hasattr(user, 'coach_profile'):
            # Coaches can only see records from their teams
            from django.db.models import Q
            from teams.models import Team
            coach_teams = Team.objects.filter(
                Q(head_coach=user.coach_profile) | Q(assistant_coach=user.coach_profile)
            )
            return queryset.filter(session__team__in=coach_teams)
        elif hasattr(user, 'player_profile'):
            # Players can only see their own records
            return queryset.filter(player=user.player_profile)
        
        # Default: no access
        return PlayerTraining.objects.none()
    
    @staticmethod
    def get_filters(request):
        """
        Extract filters from request parameters
        
        Args:
            request: Django request object
            
        Returns:
            dict: Filter dictionary for QuerySet
        """
        filters = {}
        request_params = request.query_params
        
        # Team filter - handle both team_id (slug) and actual numeric IDs
        team_id = request_params.get('team_id')
        if team_id and team_id != 'all':
            # Check if team_id is numeric (actual ID) or string (slug)
            try:
                int(team_id)
                filters['session__team_id'] = team_id
            except ValueError:
                # team_id is a slug, not numeric ID
                filters['session__team__slug'] = team_id
        
        # Date range filters
        start_date = request_params.get('start_date')
        if start_date:
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                filters['session__date__gte'] = start_date
            except ValueError:
                pass
        
        end_date = request_params.get('end_date')
        if end_date:
            try:
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
                filters['session__date__lte'] = end_date
            except ValueError:
                pass
        
        return filters

    @staticmethod
    def calculate_attendance_overview(base_queryset, filters):
        """
        Calculate attendance overview statistics
        
        Args:
            base_queryset: Base PlayerTraining queryset
            filters: Dictionary of filters to apply
            
        Returns:
            dict: Overview statistics
        """
        attendance_qs = base_queryset.filter(**filters)
        
        if not attendance_qs.exists():
            return {
                'total_sessions': 0,
                'total_players': 0,
                'total_records': 0,
                'overall_attendance_rate': 0,
                'average_attendance_per_session': 0,
                'attendance_distribution': {}
            }
        
        # Basic counts
        total_records = attendance_qs.count()
        total_sessions = attendance_qs.values('session').distinct().count()
        total_players = attendance_qs.values('player').distinct().count()
        
        # Attendance distribution
        distribution = attendance_qs.values('attendance_status').annotate(
            count=Count('id')
        )
        
        attendance_distribution = {}
        for item in distribution:
            attendance_status = item['attendance_status'] or 'pending'
            attendance_distribution[attendance_status] = item['count']
        
        # Calculate rates - include both present and late as "attended"
        present_count = attendance_distribution.get('present', 0)
        late_count = attendance_distribution.get('late', 0)
        attended_count = present_count + late_count
        overall_rate = (attended_count / total_records * 100) if total_records > 0 else 0
        
        # Average attended players per session
        avg_attended_per_session = attended_count / total_sessions if total_sessions > 0 else 0
        
        return {
            'total_sessions': total_sessions,
            'total_players': total_players,
            'total_records': total_records,
            'overall_attendance_rate': round(overall_rate, 2),
            'average_attendance_per_session': round(avg_attended_per_session, 2),
            'attendance_distribution': attendance_distribution
        }

    @staticmethod
    def calculate_attendance_trends(base_queryset, filters, period='daily'):
        """
        Calculate attendance trends over time
        
        Args:
            base_queryset: Base PlayerTraining queryset
            filters: Dictionary of filters to apply
            period: Aggregation period ('daily', 'weekly', 'monthly')
            
        Returns:
            list: Trend data points
        """
        attendance_qs = base_queryset.filter(**filters)
        
        # Get unique session dates
        session_dates = attendance_qs.values_list(
            'session__date', flat=True
        ).distinct().order_by('session__date')
        
        trends_data = []
        for date in session_dates:
            day_records = attendance_qs.filter(session__date=date)
            total = day_records.count()
            present = day_records.filter(attendance_status='present').count()
            late = day_records.filter(attendance_status='late').count()
            attended = present + late
            
            attendance_rate = (attended / total * 100) if total > 0 else 0
            
            trends_data.append({
                'date': date.isoformat(),
                'attendance_rate': round(attendance_rate, 2),
                'total_records': total,
                'present_count': present,
                'late_count': late,
                'attended_count': attended
            })
        
        return trends_data

    @staticmethod
    def calculate_attendance_heatmap(base_queryset, filters):
        """
        Calculate attendance heatmap data
        
        Args:
            base_queryset: Base PlayerTraining queryset
            filters: Dictionary of filters to apply
            
        Returns:
            list: Heatmap data points
        """
        attendance_qs = base_queryset.filter(**filters)
        
        # Group by training session date
        session_dates = attendance_qs.values_list(
            'session__date', flat=True
        ).distinct().order_by('session__date')
        
        heatmap_data = []
        for date in session_dates:
            day_records = attendance_qs.filter(session__date=date)
            total = day_records.count()
            present = day_records.filter(attendance_status='present').count()
            late = day_records.filter(attendance_status='late').count()
            attended = present + late
            
            attendance_rate = (attended / total * 100) if total > 0 else 0
            
            heatmap_data.append({
                'date': date.isoformat(),
                'total_players': total,
                'present_count': present,
                'late_count': late,
                'attended_count': attended,
                'attendance_rate': round(attendance_rate, 2)            })
        
        return heatmap_data

    @staticmethod
    def calculate_player_attendance_analytics(base_queryset, filters, request=None):
        """
        Calculate individual player attendance analytics
        
        Args:
            base_queryset: Base PlayerTraining queryset
            filters: Dictionary of filters to apply
            request: Django request object for building absolute URLs
            
        Returns:
            list: Player attendance statistics
        """
        attendance_qs = base_queryset.filter(**filters).select_related(
            'player__user', 'session'
        )
          # Group by player
        player_stats = {}
        for record in attendance_qs:
            player_id = record.player.user_id
            if player_id not in player_stats:                player_stats[player_id] = {
                    'player_id': player_id,
                    'player_name': record.player.user.get_full_name(),                    'player_profile': request.build_absolute_uri(record.player.user.profile.url) if record.player.user.profile and request else None,
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
          # Calculate attendance rates and sort
        players_data = []
        for stats in player_stats.values():
            total = stats['total_sessions']
            present = stats['present_count']
            late = stats['late_count']
            attended = present + late
            attendance_rate = (attended / total * 100) if total > 0 else 0
            
            stats['attendance_rate'] = round(attendance_rate, 2)
            players_data.append(stats)
          # Sort by attendance rate
        players_data.sort(key=lambda x: x['attendance_rate'], reverse=True)
        return players_data

    @staticmethod
    def get_player_detail_analytics(player_id, base_queryset, filters, user=None, request=None):
        """
        Get detailed attendance analytics for a specific player
        
        Args:
            player_id: Player user ID
            base_queryset: Base PlayerTraining queryset
            filters: Dictionary of filters to apply
            user: Requesting user for permission checks
            request: Django request object for building absolute URLs
            
        Returns:
            dict: Detailed player analytics
        """
        # Add player filter
        filters['player__user_id'] = player_id
        
        attendance_qs = base_queryset.filter(**filters).select_related(
            'player__user', 'session'
        ).order_by('session__date')
        
        # Permission checks
        if user and not user.is_admin:
            if hasattr(user, 'player_profile'):
                # Players can only view their own data                
                if str(user.player_profile.user_id) != str(player_id):
                    raise PermissionDenied("You can only view your own attendance data")
            elif hasattr(user, 'coach_profile'):
                # Coaches can only view data for players in their teams
                from django.db.models import Q
                from teams.models import Team
                coach_teams = Team.objects.filter(
                    Q(head_coach=user.coach_profile) | Q(assistant_coach=user.coach_profile)
                )
                player_accessible = attendance_qs.filter(session__team__in=coach_teams).exists()
                if not player_accessible:
                    raise PermissionDenied("You can only view attendance data for players in your teams")
        
        if not attendance_qs.exists():
            return {
                'player_id': player_id,
                'player_name': 'Unknown Player',
                'total_sessions': 0,
                'attendance_rate': 0.0,
                'attendance_distribution': {},
                'trends': [],
                'recent_sessions': []
            }
          # Get player info from first record
        first_record = attendance_qs.first()
        player_name = first_record.player.user.get_full_name()
        player_profile = first_record.player  # Get the full player profile
        
        # Calculate overall stats
        total_sessions = attendance_qs.count()
        present_count = attendance_qs.filter(attendance_status='present').count()
        absent_count = attendance_qs.filter(attendance_status='absent').count()
        late_count = attendance_qs.filter(attendance_status='late').count()
        excused_count = attendance_qs.filter(attendance_status='excused').count()
        
        # Count both present and late as attended for attendance rate
        attended_count = present_count + late_count
        attendance_rate = (attended_count / total_sessions * 100) if total_sessions > 0 else 0
        
        # Attendance distribution - keep original counts separate
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
                'session_id': record.session.id,
                'date': record.session.date.isoformat(),
                'session_title': record.session.title,
                'status': record.attendance_status or 'pending',
                'team': record.session.team.name if record.session.team else 'Individual'            })        
        return {
            'player_id': player_id,
            'player_name': player_name,
            'player_profile': request.build_absolute_uri(player_profile.user.profile.url) if player_profile.user.profile and request else None,
            'total_sessions': total_sessions,
            'attendance_rate': round(attendance_rate, 2),
            'attendance_distribution': attendance_distribution,
            'trends': trends,
            'recent_sessions': recent_sessions
        }


class TeamAnalyticsService:
    """Service class for team-level training analytics calculations"""
      # Team Overview Metrics methods removed - this functionality has been replaced
    # by directly displaying upcoming events on the frontend

    @staticmethod
    def _calculate_team_activity_metrics(attendance_data, training_sessions):
        """Calculate team activity and engagement metrics"""
        total_sessions = attendance_data.get('total_sessions', 0)
        total_players = attendance_data.get('total_players', 0)
        total_records = attendance_data.get('total_records', 0)
        
        # Calculate average attendance per session
        avg_attendance = total_records / total_sessions if total_sessions > 0 else 0
        
        # Estimate sessions per week (assuming recent data covers last 30 days)
        sessions_per_week = (total_sessions / 4.3) if total_sessions > 0 else 0  # 4.3 weeks in month
        
        # Active players (those who have attended at least one session)
        active_players = total_players
        
        return {
            'total_sessions': total_sessions,
            'active_players': active_players,
            'sessions_per_week': round(sessions_per_week, 1),
            'average_session_attendance': round(avg_attendance, 1)
        }    @staticmethod
    def _calculate_participation_insights(attendance_data):
        """Calculate insights about player participation patterns"""
        distribution = attendance_data.get('attendance_distribution', {})
        total_records = attendance_data.get('total_records', 1)
        overall_rate = attendance_data.get('overall_attendance_rate', 0)
        
        # Determine engagement level
        # If there's no meaningful data, don't penalize with poor engagement
        if total_records == 0:
            engagement_level = 'moderate'  # Neutral baseline for no data
        elif overall_rate >= 85:
            engagement_level = 'excellent'
        elif overall_rate >= 75:
            engagement_level = 'good'
        elif overall_rate >= 60:
            engagement_level = 'moderate'
        else:
            engagement_level = 'needs_improvement'
        
        # Calculate retention rate (present + late vs total)
        attended = distribution.get('present', 0) + distribution.get('late', 0)
        retention_rate = (attended / total_records) * 100 if total_records > 0 else 0
        
        # Determine attendance pattern
        present_ratio = distribution.get('present', 0) / total_records if total_records > 0 else 0
        late_ratio = distribution.get('late', 0) / total_records if total_records > 0 else 0
        
        if present_ratio > 0.8:
            pattern = 'excellent'
        elif present_ratio > 0.6:
            pattern = 'good'
        elif late_ratio > 0.2:
            pattern = 'irregular'
        else:
            pattern = 'concerning'
        
        return {
            'most_active_period': 'Recent weeks',  # Would be calculated from actual date analysis
            'attendance_pattern': pattern,
            'player_retention_rate': round(retention_rate, 1),
            'engagement_level': engagement_level
        }

    @staticmethod
    def _calculate_recent_trends(attendance_data, training_sessions):
        """Calculate recent performance trends"""
        overall_rate = attendance_data.get('overall_attendance_rate', 0)
        total_sessions = attendance_data.get('total_sessions', 0)
        
        # For simplicity, using overall rate as recent week rate
        # In a real implementation, this would analyze recent sessions specifically
        last_week_attendance = overall_rate
        
        # Determine trend direction
        if overall_rate >= 80:
            trend_direction = 'improving'
            improvement_percentage = round(overall_rate - 70, 1)
        elif overall_rate >= 60:
            trend_direction = 'stable'
            improvement_percentage = 0
        else:
            trend_direction = 'declining'
            improvement_percentage = round(overall_rate - 70, 1)
        
        # Generate streak info
        if total_sessions >= 5 and overall_rate >= 80:
            streak_info = f'Strong attendance streak over {total_sessions} sessions'
        elif total_sessions >= 3:
            streak_info = f'Recent activity: {total_sessions} sessions tracked'
        else:
            streak_info = 'Limited recent session data'
        
        return {
            'last_week_attendance': round(last_week_attendance, 1),
            'trend_direction': trend_direction,
            'improvement_percentage': improvement_percentage,
            'streak_info': streak_info
        }

    @staticmethod
    def _calculate_overall_summary_score(performance_metrics, activity_metrics, participation_insights):
        """Calculate an overall summary score for the team"""
        attendance_weight = 0.4
        activity_weight = 0.3
        engagement_weight = 0.3
        
        # Attendance component
        attendance_score = performance_metrics['overall_attendance_rate']
        
        # Activity component (based on sessions per week)
        sessions_per_week = activity_metrics['sessions_per_week']
        activity_score = min(100, (sessions_per_week / 3) * 100)  # 3 sessions per week = 100%
        
        # Engagement component
        engagement_mapping = {
            'excellent': 95,
            'good': 80,
            'moderate': 65,
            'needs_improvement': 40
        }
        engagement_score = engagement_mapping.get(participation_insights['engagement_level'], 50)
        
        summary_score = (
            attendance_score * attendance_weight +
            activity_score * activity_weight +
            engagement_score * engagement_weight
        )
        return round(summary_score, 1)


class TrainingEfficiencyService:
    """Service class for training efficiency and engagement calculations"""

    @staticmethod
    def calculate_training_effectiveness_score(team_slug, training_data, attendance_data):
        """
        Calculate training effectiveness score for a team
        
        Args:
            team_slug: Team identifier
            training_data: Training session data
            attendance_data: Attendance analytics data
            
        Returns:
            float: Training effectiveness score (0-100)
        """
        if not attendance_data:
            return 50.0
        
        # Base score from attendance rate
        attendance_rate = attendance_data.get('overall_attendance_rate', 0)
        effectiveness = attendance_rate
        
        # Factor in session frequency
        total_sessions = attendance_data.get('total_sessions', 0)
        if total_sessions >= 12:  # 3+ sessions per week over a month
            effectiveness += 8
        elif total_sessions >= 8:  # 2 sessions per week
            effectiveness += 5
        elif total_sessions < 4:  # Less than weekly
            effectiveness -= 5
        
        # Factor in player consistency
        if attendance_data.get('attendance_distribution'):
            dist = attendance_data['attendance_distribution']
            total_records = attendance_data.get('total_records', 1)
            consistent_attendance = (dist.get('present', 0) + dist.get('late', 0)) / total_records
            
            if consistent_attendance >= 0.8:
                effectiveness += 10
            elif consistent_attendance >= 0.7:
                effectiveness += 5
        
        return max(0, min(100, round(effectiveness, 1)))

    @staticmethod
    def process_weekly_training_aggregation(training_data, attendance_trends):
        """
        Process training data into weekly aggregations with attendance rates
        
        Args:
            training_data: Raw training session data
            attendance_trends: Attendance trend data by date
            
        Returns:
            list: Weekly aggregated training data
        """
        if not training_data:
            return []
        
        # Create attendance rates map by date
        attendance_rates_by_date = {}
        if attendance_trends:
            for trend in attendance_trends:
                attendance_rates_by_date[trend['date']] = trend['attendance_rate']
        
        # Group trainings by week
        weekly_data = {}
        
        for training in training_data:
            date = training.get('date')
            if not date:
                continue
                
            from datetime import datetime
            training_date = datetime.strptime(date, '%Y-%m-%d') if isinstance(date, str) else date
            
            # Get week start (Monday)
            weekday = training_date.weekday()
            week_start = training_date - timedelta(days=weekday)
            week_key = f"Week {week_start.strftime('%b %d')}"
            
            if week_key not in weekly_data:
                weekly_data[week_key] = {
                    'sessions': 0,
                    'total_players': 0,
                    'total_duration': 0,
                    'count': 0,
                    'attendance_rates': []
                }
            
            week_data = weekly_data[week_key]
            week_data['sessions'] += 1
            week_data['total_players'] += training.get('players_count', 0)
            week_data['total_duration'] += training.get('duration_minutes', 120)
            week_data['count'] += 1
            
            # Add attendance rate if available
            date_key = training_date.strftime('%Y-%m-%d')
            if date_key in attendance_rates_by_date:
                week_data['attendance_rates'].append(attendance_rates_by_date[date_key])
        
        # Convert to final format
        return [
            {
                'week': week,
                'sessions': data['sessions'],
                'attendance_rate': round(sum(data['attendance_rates']) / len(data['attendance_rates'])) if data['attendance_rates'] else 0,
                'avg_duration': round(data['total_duration'] / data['count']) if data['count'] > 0 else 0,
                'total_participation': data['total_players']
            }
            for week, data in sorted(weekly_data.items(), key=lambda x: x[0])
        ][-8:]  # Last 8 weeks
