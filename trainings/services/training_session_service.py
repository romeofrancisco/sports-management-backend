"""
Training Session Service

This module contains business logic for training session operations,
extracted from the TrainingSessionViewSet to improve code organization.
"""

from django.db.models import Count, Avg, Max, Min
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response

from ..models import TrainingSession, PlayerTraining, TrainingMetric, PlayerMetricRecord
from teams.models import Player


class TrainingSessionService:
    """Service class for training session operations"""

    @staticmethod
    def add_players_to_session(session, player_ids=None, attendance_status='present'):
        """
        Add multiple players to a training session
        
        Args:
            session: TrainingSession instance
            player_ids: List of player IDs to add (optional)
            attendance_status: Default attendance status for added players
            
        Returns:
            dict: Result with added count and details
        """
        # If no player_ids provided and session is a team session, add all team players
        if not player_ids and session.training_type == 'team' and session.team:
            player_ids = list(session.team.players.values_list('user_id', flat=True))

        if not player_ids:
            return {
                'success': False,
                'error': "No player IDs provided and session is not a team session or team has no players.",
                'status_code': status.HTTP_400_BAD_REQUEST
            }

        # Get existing player trainings for this session
        existing_players = set(
            PlayerTraining.objects.filter(
                session=session
            ).values_list('player_id', flat=True)
        )

        # Add players not already in the session
        added_count = 0
        added_players = []
        
        with transaction.atomic():
            for player_id in player_ids:
                if player_id not in existing_players:
                    try:
                        player = Player.objects.get(user_id=player_id)
                        PlayerTraining.objects.create(
                            session=session,
                            player=player,
                            attendance_status=attendance_status
                        )
                        added_count += 1
                        added_players.append({
                            'player_id': player_id,
                            'player_name': player.user.get_full_name()
                        })
                    except Player.DoesNotExist:
                        continue

        return {
            'success': True,
            'added_count': added_count,
            'added_players': added_players,
            'message': f"Added {added_count} players to training session"
        }

    @staticmethod
    def get_session_analytics(session):
        """
        Calculate analytics for a specific training session
        
        Args:
            session: TrainingSession instance
            
        Returns:
            dict: Analytics data including attendance and metrics summary
        """
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
            'pending': 0,
        }
        total_players = 0
        
        for stat in attendance_stats:
            status = stat['attendance_status']
            count = stat['count']
            if status in attendance_data:
                attendance_data[status] = count
            total_players += count
        
        # Calculate percentages for attendance
        attendance_data_percentages = {}
        for status in attendance_data:
            if total_players > 0:
                percentage = round((attendance_data[status] / total_players) * 100, 2)
                attendance_data_percentages[f'{status}_percentage'] = percentage
            else:
                attendance_data_percentages[f'{status}_percentage'] = 0
        
        # Merge percentages into attendance data
        attendance_data_with_percentages = {**attendance_data, **attendance_data_percentages}
        
        # Get metrics recorded in this session
        metrics_summary = PlayerMetricRecord.objects.filter(
            player_training__session=session
        ).values('metric__name', 'metric__metric_unit__code', 'metric__is_lower_better').annotate(
            avg_value=Avg('value'),
            min_value=Min('value'),
            max_value=Max('value'),
            records_count=Count('id')
        )

        return {
            'total_players': total_players,
            'attendance': attendance_data_with_percentages,
            'metrics_summary': list(metrics_summary)
        }

    @staticmethod
    def auto_add_team_players(session):
        """
        Automatically add all team players when a team session is created
        
        Args:
            session: TrainingSession instance
        """
        if session.training_type == 'team' and session.team:
            player_ids = list(session.team.players.values_list('user_id', flat=True))
            existing_players = set(
                PlayerTraining.objects.filter(session=session).values_list('player_id', flat=True)
            )
            
            with transaction.atomic():
                for player_id in player_ids:
                    if player_id not in existing_players:
                        try:
                            player = Player.objects.get(user_id=player_id)
                            PlayerTraining.objects.create(
                                session=session,
                                player=player,
                                attendance_status='pending'
                            )
                        except Player.DoesNotExist:
                            continue

    @staticmethod
    def assign_metrics_to_session(session, metric_ids):
        """
        Assign specific metrics to a training session and create records for all players
        
        Args:
            session: TrainingSession instance
            metric_ids: List of metric IDs to assign
            
        Returns:
            dict: Result with assignment details
        """
        if not isinstance(metric_ids, list):
            return {
                'success': False,
                'error': "Metrics must be provided as a list of IDs",
                'status_code': status.HTTP_400_BAD_REQUEST
            }
            
        # Get existing metrics to validate IDs
        valid_metrics = TrainingMetric.objects.filter(id__in=metric_ids)
        valid_metric_ids = set(valid_metrics.values_list('id', flat=True))
        
        # Create a list to track which metrics were not found
        invalid_metrics = [mid for mid in metric_ids if mid not in valid_metric_ids]
        
        with transaction.atomic():
            # Assign metrics to session
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

        return {
            'success': True,
            'assigned_count': len(valid_metric_ids),
            'invalid_metrics': invalid_metrics if invalid_metrics else None,
            'created_records': created_records,
            'updated_records': updated_records,
            'message': f"Assigned {len(valid_metric_ids)} metrics to training session"
        }
