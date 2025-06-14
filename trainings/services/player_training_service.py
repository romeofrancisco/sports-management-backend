"""
Player Training Service

This module contains business logic for player training operations,
extracted from the PlayerTrainingViewSet to improve code organization.
"""

from django.db import transaction
from rest_framework import status

from ..models import PlayerTraining, TrainingMetric, PlayerMetricRecord


class PlayerTrainingService:
    """Service class for player training operations"""

    @staticmethod
    def record_multiple_metrics(player_training, metrics_data, recorded_by_user=None):
        """
        Record multiple metrics for a player's training
        
        Args:
            player_training: PlayerTraining instance
            metrics_data: List of metric data to record
            recorded_by_user: User who is recording the metrics
            
        Returns:
            dict: Result with recorded metrics details
        """
        if not metrics_data:
            return {
                'success': False,
                'error': "No metrics data provided",
                'status_code': status.HTTP_400_BAD_REQUEST
            }
        
        created_records = []
        
        with transaction.atomic():
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
                            'recorded_by_id': getattr(recorded_by_user, 'coach_profile_id', None)
                        }
                    )
                    
                    created_records.append({
                        'id': record.id,
                        'metric': metric.name,
                        'value': record.value,
                        'created': created
                    })
                    
                except TrainingMetric.DoesNotExist:
                    continue        # Get previous records for comparison
        previous_records = PlayerTrainingService._get_previous_records(player_training)

        return {
            'success': True,
            'records': created_records,
            'previous_records': previous_records,
            'message': f"Recorded {len(created_records)} metrics"
        }

    @staticmethod
    def assign_metrics_to_player_training(player_training, metric_ids):
        """
        Assign specific metrics to a player's training record
        
        Args:
            player_training: PlayerTraining instance
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
        valid_metrics = set(TrainingMetric.objects.filter(
            id__in=metric_ids
        ).values_list('id', flat=True))
        
        # Create a list to track which metrics were not found
        invalid_metrics = [mid for mid in metric_ids if mid not in valid_metrics]
        
        with transaction.atomic():
            # Get currently assigned metrics before updating
            currently_assigned = set(player_training.assigned_metrics.values_list('id', flat=True))
            
            # Assign new metrics to player training
            player_training.assigned_metrics.set(valid_metrics)
            
            # Find metrics that were removed (in currently_assigned but not in valid_metrics)
            removed_metrics = currently_assigned - valid_metrics
            
            # Delete PlayerMetricRecord objects for removed metrics
            deleted_count = 0
            if removed_metrics:
                deleted_count = PlayerMetricRecord.objects.filter(
                    player_training=player_training,
                    metric_id__in=removed_metrics
                ).delete()[0]
            
            # Create placeholder PlayerMetricRecord instances for the assigned metrics
            # Only create records that don't already exist
            created_records = []
            
            for metric_id in valid_metrics:
                # Check if a record already exists for this metric and player training
                existing_record = PlayerMetricRecord.objects.filter(
                    player_training=player_training,
                    metric_id=metric_id
                ).first()
                
                if not existing_record:
                    # Create a placeholder record with value None
                    record = PlayerMetricRecord.objects.create(
                        player_training=player_training,
                        metric_id=metric_id,
                        value=None,  # Placeholder value
                        notes=""
                    )
                    created_records.append(record.id)
                    
        return {
            'success': True,
            'count': len(valid_metrics),
            'invalid_metrics': invalid_metrics if invalid_metrics else None,
            'created_records': created_records,
            'deleted_count': deleted_count,
            'message': f"Assigned {len(valid_metrics)} metrics to player training record. Removed {deleted_count} previous metric records."
        }

    @staticmethod
    def update_attendance(player_training, new_status, notes=None):
        """
        Update attendance status for a player's training record
        
        Args:
            player_training: PlayerTraining instance
            new_status: New attendance status
            notes: Optional notes
            
        Returns:
            dict: Result with update details
        """
        valid_statuses = ['present', 'absent', 'late', 'excused', 'pending']
        
        if new_status not in valid_statuses:
            return {
                'success': False,
                'error': "Invalid attendance status.",
                'status_code': status.HTTP_400_BAD_REQUEST
            }
            
        player_training.attendance_status = new_status
        if notes is not None:
            player_training.notes = notes
        player_training.save()
        
        return {
            'success': True,
            'attendance_status': new_status,
            'notes': player_training.notes,
            'message': "Attendance updated."
        }

    @staticmethod
    def bulk_update_attendance(session_id, player_records):
        """
        Update attendance status for multiple player training records
        
        Args:
            session_id: ID of the training session
            player_records: List of player record updates
            
        Returns:
            dict: Result with bulk update details
        """
        valid_statuses = ['present', 'absent', 'late', 'excused', 'pending']
        
        if not session_id:
            return {
                'success': False,
                'error': "Session ID is required.",
                'status_code': status.HTTP_400_BAD_REQUEST
            }
        
        if not player_records:
            return {
                'success': False,
                'error': "No player records provided.",
                'status_code': status.HTTP_400_BAD_REQUEST
            }
        
        # Track updated records and any errors
        updated_count = 0
        errors = []
        updated_players = []
        
        with transaction.atomic():
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
                    updated_players.append({
                        'id': record_id,
                        'player_name': player_training.player.user.get_full_name(),
                        'status': new_status
                    })
                except PlayerTraining.DoesNotExist:
                    errors.append(f"Record {record_id} not found")

        return {
            'success': True,
            'updated_count': updated_count,
            'updated_players': updated_players,
            'errors': errors if errors else None,
            'message': f"Updated {updated_count} attendance records"
        }

    @staticmethod
    def _get_previous_records(player_training):
        """
        Get previous records for this player across metrics
        
        Args:
            player_training: PlayerTraining instance
            
        Returns:
            list: Previous metric records
        """
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

    @staticmethod
    def get_previous_records(player_training):
        """
        Public method to get previous records for this player
        
        Args:
            player_training: PlayerTraining instance
            
        Returns:
            dict: Previous records data
        """
        previous_records = PlayerTrainingService._get_previous_records(player_training)
        
        return {
            'success': True,
            'previous_records': previous_records
        }

    @staticmethod
    def get_previous_record_for_metric(player_training, metric_id):
        """
        Get the previous record for a specific metric for this player
        
        Args:
            player_training: PlayerTraining instance
            metric_id: ID of the specific metric to look for
            
        Returns:
            dict: Previous metric record with normalization weight info or None if not found
        """
        player = player_training.player
        current_session = player_training.session
        
        # Find the most recent training session before this one that has this specific metric
        previous_records = PlayerMetricRecord.objects.filter(
            player_training__player=player,
            player_training__session__date__lt=current_session.date,
            metric_id=metric_id
        ).select_related(
            'metric', 
            'metric__metric_unit',
            'player_training__session'
        ).order_by('-player_training__session__date')
        
        if not previous_records.exists():
            return None
            
        previous_record = previous_records.first()
        
        return {
            'metric_id': previous_record.metric.id,
            'metric_name': previous_record.metric.name,
            'value': previous_record.value,
            'notes': previous_record.notes,
            'session_date': previous_record.player_training.session.date,
            'session_title': previous_record.player_training.session.title,
            'unit': previous_record.metric.metric_unit.code if previous_record.metric.metric_unit else '-',
            'is_lower_better': previous_record.metric.is_lower_better,
            'normalization_weight': float(previous_record.metric.metric_unit.normalization_weight) if previous_record.metric.metric_unit else 1.0
        }
