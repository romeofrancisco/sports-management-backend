from django.db.models import Count, Avg, Max, Min, Q, F
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import statistics

from trainings.models import PlayerMetricRecord, PlayerTraining, TrainingSession, TrainingMetric
from trainings.services.performance_service import PerformanceService
from trainings.utils import calculate_normalized_improvement


class TrainingCompletionService:
    """Service for generating training completion summaries with improvements and recommendations"""
    
    @staticmethod
    def generate_training_summary(session, request=None):
        """
        Generate a comprehensive training summary when a session is completed
        
        Args:
            session: TrainingSession instance
            request: HttpRequest instance for building absolute URIs
            
        Returns:
            dict: Training summary with improvements, statistics, and recommendations
        """
        
        # Basic session information
        session_info = {
            'session_id': session.id,
            'title': session.title,
            'description': session.description,
            'date': session.date,
            'duration_minutes': session.duration_minutes,
            'location': session.location,
            'status': session.status,
            'notes': session.notes,
            'team': {
                'id': session.team.id,
                'name': session.team.name
            } if session.team else None
        }
        
        # Attendance summary
        attendance_summary = TrainingCompletionService._calculate_attendance_summary(session)
        
        # Metrics summary and improvements
        metrics_summary = TrainingCompletionService._calculate_metrics_summary(session)
        
        # Player improvements
        player_improvements = TrainingCompletionService._calculate_player_improvements(session, request)
        
        # Training recommendations
        recommendations = TrainingCompletionService._generate_recommendations(
            session, attendance_summary, metrics_summary, player_improvements
        )
        
        # Overall training effectiveness score
        effectiveness_score = TrainingCompletionService._calculate_effectiveness_score(
            attendance_summary, metrics_summary, player_improvements
        )
        
        return {
            'session_info': session_info,
            'attendance_summary': attendance_summary,
            'metrics_summary': metrics_summary,
            'player_improvements': player_improvements,
            'recommendations': recommendations,
            'effectiveness_score': effectiveness_score,
            'generated_at': timezone.now().isoformat()
        }
    
    @staticmethod
    def _calculate_attendance_summary(session):
        """Calculate attendance statistics for the session"""
        
        attendance_stats = PlayerTraining.objects.filter(
            session=session
        ).values('attendance_status').annotate(count=Count('id'))
        
        attendance_data = {
            'present': 0,
            'absent': 0,
            'late': 0,
            'excused': 0,
            'pending': 0,
        }
        total_players = 0
        
        for stat in attendance_stats:
            status = stat['attendance_status']
            count = stat['count']
            if status in attendance_data:
                attendance_data[status] = count
            total_players += count
        
        # Calculate attendance rate
        effective_attendance = attendance_data['present'] + attendance_data['late']
        attendance_rate = (effective_attendance / total_players * 100) if total_players > 0 else 0
        
        return {
            'total_players': total_players,
            'present': attendance_data['present'],
            'late': attendance_data['late'],
            'absent': attendance_data['absent'],
            'excused': attendance_data['excused'],
            'pending': attendance_data['pending'],
            'attendance_rate': round(attendance_rate, 1),
            'effective_attendance': effective_attendance
        }
    
    @staticmethod
    def _calculate_metrics_summary(session):
        """Calculate metrics recording statistics and improvements"""
        
        # Get all metric records for this session
        metric_records = PlayerMetricRecord.objects.filter(
            player_training__session=session,
            value__isnull=False
        ).select_related('metric', 'metric__metric_unit', 'player_training__player')
        
        if not metric_records.exists():
            return {
                'total_metrics_recorded': 0,
                'unique_metrics': 0,
                'players_with_metrics': 0,
                'metrics_breakdown': [],
                'completion_rate': 0
            }
          # Calculate basic statistics
        total_records = metric_records.count()
        unique_metrics = metric_records.values('metric').distinct().count()
        players_with_metrics = metric_records.values('player_training__player').distinct().count()
        
        # Get metrics breakdown
        metrics_breakdown = metric_records.values(
            'metric__id',
            'metric__name',
            'metric__metric_unit__code',
            'metric__is_lower_better'
        ).annotate(
            records_count=Count('id'),
            avg_value=Avg('value'),
            min_value=Min('value'),
            max_value=Max('value'),
            unique_players=Count('player_training__player', distinct=True)
        )# Calculate expected records more accurately by counting actual assigned metrics
        # Only count players who were present or late (could reasonably record metrics)
        participating_players = PlayerTraining.objects.filter(
            session=session,
            attendance_status__in=['present', 'late']
        )
        
        # Calculate expected records based on actual assignments
        expected_records = 0
        for player_training in participating_players:
            # Get assigned metrics for this specific player
            player_assigned_metrics = player_training.assigned_metrics.count()
            
            # If no specific assignments, use session-level metrics
            if player_assigned_metrics == 0:
                player_assigned_metrics = session.metrics.count()
            
            # If still no metrics, use the unique metrics that have records
            if player_assigned_metrics == 0:
                player_assigned_metrics = unique_metrics
            
            expected_records += player_assigned_metrics
        
        # Calculate completion rate based on unique player-metric combinations to avoid >100%
        # Count unique player-metric combinations that were actually recorded
        unique_combinations_recorded = metric_records.values(
            'player_training__player', 'metric'
        ).distinct().count()
        
        completion_rate = (unique_combinations_recorded / expected_records * 100) if expected_records > 0 else 0
        
        return {
            'total_metrics_recorded': total_records,
            'unique_metrics': unique_metrics,
            'players_with_metrics': players_with_metrics,
            'metrics_breakdown': list(metrics_breakdown),
            'completion_rate': round(completion_rate, 1),
            'expected_records': expected_records
        }
    @staticmethod
    def _calculate_player_improvements(session, request=None):
        """Calculate individual player improvements during this session"""
        
        improvements = []
        
        # Get ALL players who participated in this session (regardless of metric records)
        all_players = PlayerTraining.objects.filter(
            session=session
        ).select_related('player')
        
        for player_training in all_players:
            player = player_training.player
            
            # Build profile URL with request context
            profile_url = None
            if player.user.profile:
                if request:
                    profile_url = request.build_absolute_uri(player.user.profile.url)
                else:
                    profile_url = player.user.profile.url
            
            player_improvements = {
                'player_id': player.user.id,
                'player_name': f"{player.user.first_name} {player.user.last_name}",
                'player_profile': profile_url,
                'metrics_recorded': 0,
                'metric_improvements': [],
                'overall_improvement_percentage': 0,
                'attendance_status': player_training.attendance_status,
                'notes': player_training.notes
            }
            
            # Get current session metrics for this player
            current_records = PlayerMetricRecord.objects.filter(
                player_training=player_training,
                value__isnull=False
            ).select_related('metric')
            
            total_improvement_percentage = 0
            improvement_count = 0
            
            for current_record in current_records:
                # Find previous record for the same metric
                previous_record = PlayerMetricRecord.objects.filter(
                    player_training__player=player,
                    metric=current_record.metric,
                    player_training__session__date__lt=session.date,
                    value__isnull=False                ).order_by('-player_training__session__date').first()
                
                metric_improvement = {
                    'metric_id': current_record.metric.id,
                    'metric_name': current_record.metric.name,
                    'current_value': float(current_record.value),
                    'unit': current_record.metric.metric_unit.code if current_record.metric.metric_unit else '',
                    'is_lower_better': current_record.metric.is_lower_better,
                    'has_previous_record': previous_record is not None,
                    'notes': current_record.notes
                }
                
                if previous_record:
                    # Calculate improvement using the shared utility function
                    normalization_weight = 1.0
                    if current_record.metric.metric_unit and current_record.metric.metric_unit.normalization_weight:
                        normalization_weight = float(current_record.metric.metric_unit.normalization_weight)
                    
                    improvement_data = calculate_normalized_improvement(
                        float(current_record.value),
                        float(previous_record.value),
                        current_record.metric.is_lower_better,
                        normalization_weight
                    )
                    
                    metric_improvement.update({
                        'previous_value': float(previous_record.value),
                        'raw_difference': improvement_data['raw_value'],
                        'improvement_percentage': improvement_data['percentage'],
                        'is_improvement': improvement_data['percentage'] > 0,
                        'previous_session_date': previous_record.player_training.session.date
                    })
                    
                    total_improvement_percentage += improvement_data['percentage']
                    improvement_count += 1
                else:
                    metric_improvement.update({
                        'previous_value': None,
                        'raw_difference': None,
                        'improvement_percentage': None,
                        'is_improvement': None,
                        'previous_session_date': None,
                        'note': 'First time recording this metric'
                    })
                
                player_improvements['metric_improvements'].append(metric_improvement)
            
            player_improvements['metrics_recorded'] = len(player_improvements['metric_improvements'])
            
            # Calculate overall improvement percentage for this player
            if improvement_count > 0:
                player_improvements['overall_improvement_percentage'] = round(
                    total_improvement_percentage / improvement_count, 2
                )
            
            improvements.append(player_improvements)
        
        # Sort players by overall improvement
        improvements.sort(
            key=lambda x: x['overall_improvement_percentage'] if x['overall_improvement_percentage'] else -999,
            reverse=True
        )
        
        return improvements
    
    @staticmethod
    def _generate_recommendations(session, attendance_summary, metrics_summary, player_improvements):
        """Generate training recommendations based on session data"""
        
        recommendations = {
            'attendance_recommendations': [],
            'metrics_recommendations': [],
            'player_development_recommendations': [],
            'general_recommendations': []
        }
        
        # Attendance recommendations
        attendance_rate = attendance_summary['attendance_rate']
        if attendance_rate < 70:
            recommendations['attendance_recommendations'].append({
                'priority': 'high',
                'category': 'attendance',
                'message': f"Low attendance rate ({attendance_rate}%). Consider reviewing session scheduling and player communication.",
                'suggestion': 'Send reminders 24-48 hours before sessions and gather feedback on optimal training times.'
            })
        elif attendance_rate < 85:
            recommendations['attendance_recommendations'].append({
                'priority': 'medium',
                'category': 'attendance',
                'message': f"Good attendance rate ({attendance_rate}%) but room for improvement.",
                'suggestion': 'Maintain current communication strategies and consider incentives for consistent attendance.'
            })
        
        # Metrics recommendations
        completion_rate = metrics_summary['completion_rate']
        if completion_rate < 60:
            recommendations['metrics_recommendations'].append({
                'priority': 'high',
                'category': 'metrics',
                'message': f"Low metrics completion rate ({completion_rate}%). Many performance measurements are missing.",
                'suggestion': 'Streamline the metrics recording process and ensure coaches have adequate time for data collection.'
            })
        elif completion_rate < 80:
            recommendations['metrics_recommendations'].append({
                'priority': 'medium',
                'category': 'metrics',
                'message': f"Moderate metrics completion rate ({completion_rate}%). Some performance data is missing.",
                'suggestion': 'Review which metrics are most challenging to record and consider simplifying the process.'
            })
        
        # Player development recommendations
        if player_improvements:
            improving_players = [p for p in player_improvements if p['overall_improvement_percentage'] > 0]
            declining_players = [p for p in player_improvements if p['overall_improvement_percentage'] < -5]
            
            if len(improving_players) > len(player_improvements) * 0.7:
                recommendations['player_development_recommendations'].append({
                    'priority': 'positive',
                    'category': 'development',
                    'message': f"Excellent progress! {len(improving_players)} out of {len(player_improvements)} players showed improvement.",
                    'suggestion': 'Continue current training methods and consider sharing successful strategies across the team.'
                })
            
            if declining_players:
                recommendations['player_development_recommendations'].append({
                    'priority': 'medium',
                    'category': 'development',
                    'message': f"{len(declining_players)} players showed declining performance in some metrics.",
                    'suggestion': 'Provide additional support and personalized training plans for struggling players.'
                })
        
        # General recommendations based on session characteristics
        if session.duration_minutes and session.duration_minutes > 150:
            recommendations['general_recommendations'].append({
                'priority': 'low',
                'category': 'session_structure',
                'message': 'Extended training session duration.',
                'suggestion': 'Consider breaking longer sessions into focused segments to maintain player engagement and energy.'
            })
        
        if metrics_summary['unique_metrics'] > 8:
            recommendations['general_recommendations'].append({
                'priority': 'medium',
                'category': 'metrics_management',
                'message': f"High number of metrics tracked ({metrics_summary['unique_metrics']}).",
                'suggestion': 'Focus on 4-6 key performance indicators per session to avoid data overload and improve recording accuracy.'
            })
        
        return recommendations
    
    @staticmethod
    def _calculate_effectiveness_score(attendance_summary, metrics_summary, player_improvements):
        """Calculate an overall training effectiveness score (0-100)"""
        
        # Attendance component (30% weight)
        attendance_score = min(100, attendance_summary['attendance_rate'])
        
        # Metrics completion component (25% weight)
        metrics_score = min(100, metrics_summary['completion_rate'])
          # Player improvement component (35% weight)
        improvement_score = 0
        if player_improvements:
            positive_improvements = [
                p for p in player_improvements 
                if p['overall_improvement_percentage'] and p['overall_improvement_percentage'] > 0
            ]
            improvement_rate = len(positive_improvements) / len(player_improvements)
            improvement_score = improvement_rate * 100
        
        # Engagement quality component (10% weight) - measures depth of participation
        engagement_score = 0
        if attendance_summary['total_players'] > 0:
            # Calculate based on metrics per player ratio
            if metrics_summary['players_with_metrics'] > 0:
                avg_metrics_per_player = metrics_summary['total_metrics_recorded'] / metrics_summary['players_with_metrics']
                # Normalize to 0-100 scale (assuming 3+ metrics per player is excellent)
                engagement_score = min(100, (avg_metrics_per_player / 3.0) * 100)
        
        # Calculate weighted score
        effectiveness_score = (
            attendance_score * 0.30 +
            metrics_score * 0.25 +
            improvement_score * 0.35 +
            engagement_score * 0.10
        )
        
        # Determine effectiveness level
        if effectiveness_score >= 85:
            level = 'excellent'
        elif effectiveness_score >= 75:
            level = 'very_good'
        elif effectiveness_score >= 65:
            level = 'good'
        elif effectiveness_score >= 50:
            level = 'fair'
        else:
            level = 'needs_improvement'
        return {
            'score': round(effectiveness_score, 1),
            'level': level,
            'components': {
                'attendance': round(attendance_score, 1),
                'metrics_completion': round(metrics_score, 1),
                'player_improvement': round(improvement_score, 1),
                'engagement': round(engagement_score, 1)
            }
        }
