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
            dict: Result with added count and details        """
        # If no player_ids provided, add all team players since all sessions are team sessions
        if not player_ids and session.team:
            player_ids = list(session.team.players.values_list('user_id', flat=True))

        if not player_ids:
            return {
                'success': False,
                'error': "No player IDs provided and session has no team or team has no players.",
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
        attendance_data_with_percentages = {**attendance_data, **attendance_data_percentages}        # Get metrics recorded in this session
        metrics_summary = PlayerMetricRecord.objects.filter(
            player_training__session=session,
            value__isnull=False  # Only include records with actual values
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
            session: TrainingSession instance        """
        if session.team:
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
        from .player_training_service import PlayerTrainingService
        
        if not isinstance(metric_ids, list):
            return {
                'success': False,
                'error': "Metrics must be provided as a list of IDs",
                'status_code': status.HTTP_400_BAD_REQUEST
            }
            
        # Get existing metrics to validate IDs
        valid_metrics = TrainingMetric.objects.filter(id__in=metric_ids)
        valid_metric_ids = list(valid_metrics.values_list('id', flat=True))
        
        # Create a list to track which metrics were not found
        invalid_metrics = [mid for mid in metric_ids if mid not in valid_metric_ids]
        
        with transaction.atomic():
            # Assign metrics to session
            session.metrics.set(valid_metric_ids)
            
            # Get all player trainings for this session
            player_trainings = PlayerTraining.objects.filter(session=session)
            
            # Use PlayerTrainingService to properly assign metrics to each player
            # This ensures proper cleanup of removed metrics
            total_created = 0
            total_deleted = 0
            player_results = []
            
            for player_training in player_trainings:
                result = PlayerTrainingService.assign_metrics_to_player_training(
                    player_training, valid_metric_ids
                )
                if result['success']:
                    total_created += len(result.get('created_records', []))
                    total_deleted += result.get('deleted_count', 0)
                    player_results.append({
                        'player': player_training.player.user.get_full_name(),
                        'assigned': result['count'],
                        'created': len(result.get('created_records', [])),
                        'deleted': result.get('deleted_count', 0)
                    })

        return {
            'success': True,
            'assigned_count': len(valid_metric_ids),
            'invalid_metrics': invalid_metrics if invalid_metrics else None,
            'total_created_records': total_created,
            'total_deleted_records': total_deleted,
            'player_results': player_results,
            'message': f"Assigned {len(valid_metric_ids)} metrics to training session. Created {total_created} new records, deleted {total_deleted} old records."
        }
    @staticmethod
    def assign_metrics_to_players_in_session(session, player_ids, metric_ids):
        """Assign specific metrics to specific players in a training session"""
        from ..models import PlayerTraining, TrainingMetric
        from teams.models import Player
        from .player_training_service import PlayerTrainingService
        
        results = []
        errors = []        # Validate players exist and are part of this session
        valid_player_ids = []
        for player_id in player_ids:
            try:
                # Player model uses user as primary key, so we use pk directly
                player = Player.objects.get(pk=player_id)
                
                # Check if player has a PlayerTraining record for this session
                player_training = PlayerTraining.objects.get(
                    player=player, 
                    session=session
                )
                valid_player_ids.append(player_id)
            except Player.DoesNotExist:
                errors.append(f"Player with ID {player_id} does not exist")
            except PlayerTraining.DoesNotExist:
                errors.append(f"Player {player_id} is not registered for this session")# Validate metrics exist
        valid_metrics = TrainingMetric.objects.filter(id__in=metric_ids)
        valid_metric_ids = list(valid_metrics.values_list('id', flat=True))
        invalid_metrics = [mid for mid in metric_ids if mid not in valid_metric_ids]
        
        if invalid_metrics:
            errors.extend([f"Metric with ID {mid} does not exist" for mid in invalid_metrics])        # Assign metrics to each valid player
        total_added = 0
        total_removed = 0
        
        for player_id in valid_player_ids:
            try:
                # Get player first, then get PlayerTraining
                player = Player.objects.get(pk=player_id)
                player_training = PlayerTraining.objects.get(
                    player=player, 
                    session=session
                )
                
                # Use PlayerTrainingService to assign metrics
                result = PlayerTrainingService.assign_metrics_to_player_training(
                    player_training, valid_metric_ids
                )
                
                # Track totals
                total_added += len(result.get('created_records', []))
                total_removed += result.get('deleted_count', 0)
                
                results.append({
                    'player_id': player_id,
                    'player_name': player_training.player.user.get_full_name(),
                    'success': result['success'],
                    'assigned_count': result['count'],
                    'created_records': len(result.get('created_records', [])),
                    'deleted_records': result.get('deleted_count', 0)
                })
                
            except Exception as e:
                errors.append(f"Error assigning metrics to player {player_id}: {str(e)}")
        
        return {
            'success': len(errors) == 0,
            'results': results,
            'errors': errors,
            'total_players_processed': len(valid_player_ids),
            'total_metrics_assigned': len(valid_metric_ids),
            'total_metrics_added': total_added,
            'total_metrics_removed': total_removed,
            'invalid_metrics': invalid_metrics
        }
        
    @staticmethod
    def assign_metrics_to_single_player(session, player_id, metric_ids):
        """Assign specific metrics to a single player in a training session"""
        from ..models import PlayerTraining, TrainingMetric
        from teams.models import Player
        from .player_training_service import PlayerTrainingService
        
        try:
            # Player model uses user as primary key, so we use pk directly
            player = Player.objects.get(pk=player_id)
            
            # Check if player has a PlayerTraining record for this session
            player_training = PlayerTraining.objects.get(
                player=player, 
                session=session
            )
        except Player.DoesNotExist:
            return {
                'success': False,
                'error': f"Player with ID {player_id} does not exist",
                'status_code': status.HTTP_404_NOT_FOUND
            }
        except PlayerTraining.DoesNotExist:
            return {
                'success': False,
                'error': f"Player {player_id} is not registered for this session",
                'status_code': status.HTTP_400_BAD_REQUEST
            }

        # Validate metrics exist
        valid_metrics = TrainingMetric.objects.filter(id__in=metric_ids)
        valid_metric_ids = list(valid_metrics.values_list('id', flat=True))
        invalid_metrics = [mid for mid in metric_ids if mid not in valid_metric_ids]
        
        if invalid_metrics:
            return {
                'success': False,
                'error': f"Invalid metric IDs: {invalid_metrics}",
                'status_code': status.HTTP_400_BAD_REQUEST
            }

        # Use PlayerTrainingService to assign metrics
        result = PlayerTrainingService.assign_metrics_to_player_training(
            player_training, valid_metric_ids
        )
        
        if not result['success']:
            return {
                'success': False,
                'error': result.get('error', 'Failed to assign metrics'),
                'status_code': status.HTTP_500_INTERNAL_SERVER_ERROR
            }
        
        return {
            'success': True,
            'player_id': player_id,
            'player_name': player_training.player.user.get_full_name(),
            'assigned_count': result['count'],
            'metrics_added': len(result.get('created_records', [])),
            'metrics_removed': result.get('deleted_count', 0),
            'total_metrics': result['count'],
            'message': f"Successfully assigned {result['count']} metrics to {player_training.player.user.get_full_name()}"
        }
