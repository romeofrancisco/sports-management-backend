from django.db.models import Count, Q, Avg, Sum, F
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
from trainings.models import TrainingSession, PlayerTraining
from users.models import User


class TrainingSummaryService:
    """
    Service for providing training summary data for dashboard visualization.
    Focuses on high-level metrics and trends suitable for dashboard consumption.
    """
    
    @staticmethod
    def get_training_overview(days=30):
        """
        Get high-level training metrics for dashboard overview.
        
        Args:
            days (int): Number of days to look back for metrics
            
        Returns:
            dict: Training overview data
        """
        cutoff_date = timezone.now() - timedelta(days=days)
        try:
            # Basic counts
            total_sessions = TrainingSession.objects.count()
            active_sessions = TrainingSession.objects.filter(
                status='upcoming',
                date__gte=timezone.now().date()
            ).count()
            
            recent_sessions = TrainingSession.objects.filter(
                date__gte=cutoff_date.date()
            ).count()
            
            # Attendance metrics
            total_attendances = PlayerTraining.objects.filter(
                session__date__gte=cutoff_date.date()
            ).count()
            
            attended_count = PlayerTraining.objects.filter(
                session__date__gte=cutoff_date.date(),
                attendance_status='present'
            ).count()
            
            attendance_rate = round(
                (attended_count / total_attendances * 100) if total_attendances > 0 else 0, 1
            )
            
            # Participation metrics
            unique_participants = PlayerTraining.objects.filter(
                session__date__gte=cutoff_date.date()
            ).values('player').distinct().count()
            
            # Training frequency - average sessions per team
            avg_sessions_per_team = TrainingSession.objects.filter(
                date__gte=cutoff_date.date(),
                team__isnull=False
            ).values('team').annotate(
                session_count=Count('id')
            ).aggregate(
                avg_sessions=Avg('session_count')
            )['avg_sessions'] or 0
            
            return {
                'total_training_sessions': total_sessions,
                'active_training_sessions': active_sessions,
                'recent_sessions': recent_sessions,
                'attendance_rate': attendance_rate,
                'unique_participants': unique_participants,
                'avg_sessions_per_team': round(float(avg_sessions_per_team), 1),
                'period_days': days
            }
        except Exception as e:
            return {
                'total_training_sessions': 0,
                'active_training_sessions': 0,
                'recent_sessions': 0,
                'attendance_rate': 0,
                'unique_participants': 0,
                'avg_sessions_per_team': 0,
                'period_days': days,
                'error': str(e)
            }

    @staticmethod
    def get_training_trends(days=30):
        """
        Get training trends data for chart visualization.
        
        Args:
            days (int): Number of days to analyze
            
        Returns:
            dict: Trend data suitable for charts
        """
        cutoff_date = timezone.now() - timedelta(days=days)
        
        try:
            # Daily session counts
            daily_sessions = TrainingSession.objects.filter(
                date__gte=cutoff_date.date()
            ).extra(
                select={'day': 'DATE(date)'}
            ).values('day').annotate(
                session_count=Count('id'),
                attendance_count=Count('player_records')
            ).order_by('day')
            
            # Weekly attendance trends
            weekly_attendance = []
            for week in range(0, days, 7):
                week_start = timezone.now() - timedelta(days=week+7)
                week_end = timezone.now() - timedelta(days=week)
                
                week_data = PlayerTraining.objects.filter(
                    session__date__range=[week_start.date(), week_end.date()]
                ).aggregate(
                    total=Count('id'),
                    present=Count('id', filter=Q(attendance_status='present')),
                    absent=Count('id', filter=Q(attendance_status='absent'))
                )
                
                attendance_rate = (
                    week_data['present'] / week_data['total'] * 100 
                    if week_data['total'] > 0 else 0
                )
                
                weekly_attendance.append({
                    'week': f"Week {week//7 + 1}",
                    'attendance_rate': round(attendance_rate, 1),
                    'total_sessions': week_data['total'],
                    'week_start': week_start.date().isoformat(),
                    'week_end': week_end.date().isoformat()
                })
            
            # Sport distribution - based on teams that have training sessions
            sport_distribution = TrainingSession.objects.filter(
                date__gte=cutoff_date.date(),
                team__sport__isnull=False
            ).values(
                'team__sport__name'
            ).annotate(
                session_count=Count('id'),
                participant_count=Count('player_records__player', distinct=True)
            ).order_by('-session_count')
            
            return {
                'daily_sessions': list(daily_sessions),
                'weekly_attendance': weekly_attendance,
                'sport_distribution': list(sport_distribution),
                'period_days': days
            }
            
        except Exception as e:
            return {
                'daily_sessions': [],
                'weekly_attendance': [],
                'sport_distribution': [],
                'period_days': days,
                'error': str(e)
            }
    @staticmethod
    def get_training_performance(days=30):
        """
        Get training performance metrics for dashboard.
        
        Args:
            days (int): Number of days to analyze
            
        Returns:
            dict: Performance metrics
        """
        cutoff_date = timezone.now() - timedelta(days=days)
        
        try:
            # Top performing teams by training attendance
            top_teams = TrainingSession.objects.filter(
                date__gte=cutoff_date.date(),
                team__isnull=False
            ).values(
                'team__id', 'team__name'
            ).annotate(
                session_count=Count('id'),
                total_participants=Count('player_records__player', distinct=True),
                avg_attendance_rate=Avg(
                    Count('player_records', filter=Q(player_records__attendance_status='present')) * 100.0 /
                    Count('player_records')
                )
            ).order_by('-avg_attendance_rate')[:5]
            
            # Coach performance based on sessions conducted
            from users.models import User
            coach_performance = User.objects.filter(
                role='coach',
                conducted_sessions__date__gte=cutoff_date.date()
            ).annotate(
                session_count=Count('conducted_sessions'),
                total_participants=Count('conducted_sessions__player_records__player', distinct=True),
                avg_attendance_rate=Avg(
                    Count('conducted_sessions__player_records', filter=Q(conducted_sessions__player_records__attendance_status='present')) * 100.0 /
                    Count('conducted_sessions__player_records')
                )
            ).order_by('-session_count')[:5]
            
            # Training completion stats based on sessions
            completion_stats = TrainingSession.objects.aggregate(
                total=Count('id'),
                completed=Count('id', filter=Q(status='completed')),
                ongoing=Count('id', filter=Q(status='ongoing')),
                upcoming=Count('id', filter=Q(status='upcoming'))
            )
            
            completion_rate = (
                completion_stats['completed'] / completion_stats['total'] * 100
                if completion_stats['total'] > 0 else 0
            )
            
            return {
                'top_teams': [
                    {
                        'id': team['team__id'],
                        'name': team['team__name'],
                        'session_count': team['session_count'],
                        'participants': team['total_participants'],
                        'attendance_rate': round(float(team['avg_attendance_rate'] or 0), 1)
                    }
                    for team in top_teams
                ],
                'coach_performance': [
                    {
                        'id': coach.id,
                        'name': f"{coach.first_name} {coach.last_name}",
                        'session_count': coach.session_count,
                        'participants': coach.total_participants,
                        'attendance_rate': round(float(coach.avg_attendance_rate or 0), 1)
                    }
                    for coach in coach_performance
                ],
                'completion_stats': {
                    'total': completion_stats['total'],
                    'completed': completion_stats['completed'],
                    'ongoing': completion_stats['ongoing'],
                    'upcoming': completion_stats['upcoming'],
                    'completion_rate': round(completion_rate, 1)
                },
                'period_days': days
            }
            
        except Exception as e:
            return {
                'top_teams': [],
                'coach_performance': [],
                'completion_stats': {
                    'total': 0,
                    'completed': 0,
                    'ongoing': 0,
                    'upcoming': 0,
                    'completion_rate': 0
                },
                'period_days': days,
                'error': str(e)
            }
    @staticmethod
    def get_training_health_indicators():
        """
        Get training health indicators for dashboard alerts.
        
        Returns:
            dict: Health indicators and alerts
        """
        try:
            now = timezone.now()
            
            # Teams without recent training sessions
            teams_without_recent_training = TrainingSession.objects.filter(
                team__isnull=False
            ).values('team').distinct().exclude(
                date__gte=now.date() - timedelta(days=7)
            ).count()
            
            # Sessions with low attendance (last 7 days)
            recent_sessions = TrainingSession.objects.filter(
                date__gte=now.date() - timedelta(days=7),
                status='completed'
            )
            
            low_attendance_sessions = 0
            for session in recent_sessions:
                total_attendance = session.player_records.count()
                present_count = session.player_records.filter(attendance_status='present').count()
                attendance_rate = (present_count / total_attendance * 100) if total_attendance > 0 else 0
                
                if attendance_rate < 50:  # Less than 50% attendance
                    low_attendance_sessions += 1
            
            # Overdue sessions (sessions that should have been completed but aren't)
            overdue_sessions = TrainingSession.objects.filter(
                date__lt=now.date(),
                status__in=['upcoming', 'ongoing']
            ).count()
            
            # Total active teams with training sessions
            total_active_teams = TrainingSession.objects.filter(
                team__isnull=False,
                date__gte=now.date() - timedelta(days=30)
            ).values('team').distinct().count()
            
            # Calculate health score (0-100)
            if total_active_teams == 0:
                health_score = 100
            else:
                inactive_penalty = (teams_without_recent_training / max(total_active_teams, 1)) * 30
                overdue_penalty = min(overdue_sessions * 5, 40)
                low_attendance_penalty = min(low_attendance_sessions * 5, 30)
                
                health_score = max(0, 100 - inactive_penalty - overdue_penalty - low_attendance_penalty)
            
            # Determine health status
            if health_score >= 80:
                health_status = 'excellent'
            elif health_score >= 60:
                health_status = 'good'
            elif health_score >= 40:
                health_status = 'fair'
            else:
                health_status = 'poor'
            
            # Generate alerts
            alerts = []
            if teams_without_recent_training > 0:
                alerts.append({
                    'type': 'warning',
                    'message': f"{teams_without_recent_training} teams haven't had training sessions in the past week"
                })
            if overdue_sessions > 0:
                alerts.append({
                    'type': 'error',
                    'message': f"{overdue_sessions} training sessions are overdue for status update"
                })
            if low_attendance_sessions > 0:
                alerts.append({
                    'type': 'warning',
                    'message': f"{low_attendance_sessions} recent sessions had low attendance (<50%)"
                })
            
            return {
                'health_score': round(health_score, 1),
                'health_status': health_status,
                'indicators': {
                    'teams_without_recent_training': teams_without_recent_training,
                    'low_attendance_sessions': low_attendance_sessions,
                    'overdue_sessions': overdue_sessions,
                    'total_active_teams': total_active_teams
                },
                'alerts': alerts
            }
            
        except Exception as e:
            return {
                'health_score': 0,
                'health_status': 'unknown',
                'indicators': {
                    'teams_without_recent_training': 0,
                    'low_attendance_sessions': 0,
                    'overdue_sessions': 0,
                    'total_active_teams': 0
                },
                'alerts': [],
                'error': str(e)
            }
