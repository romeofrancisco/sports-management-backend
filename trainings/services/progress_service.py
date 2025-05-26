import statistics
from django.utils import timezone
from datetime import datetime
from trainings.models import PlayerMetricRecord, PlayerTraining
from trainings.utils import calculate_normalized_improvement

class ProgressService:
    """Service class for calculating player progress and improvements"""
    
    @staticmethod
    def calculate_overall_data_points(player, records_query, date_from=None, date_to=None):
        """
        Calculate overall improvement data points across all metrics
        
        Args:
            player: Player instance
            records_query: Base query for records
            date_from: Optional start date filter
            date_to: Optional end date filter
            
        Returns:
            List of data points for overall performance
        """
        from decimal import Decimal

        # Get all unique dates where metrics were recorded
        unique_dates = records_query.values_list('player_training__session__date', flat=True).distinct().order_by('player_training__session__date')
        
        if not unique_dates:
            return []
            
        overall_points = []
        
        # For each date, calculate the average improvement percentage up to that point
        prev_date = None
        
        for date in unique_dates:
            # Get all metrics recorded up to this date
            metrics_till_date = {}
            
            # Filter records up to current date
            records_till_date = PlayerMetricRecord.objects.filter(
                player_training__player=player,
                player_training__session__date__lte=date
            ).select_related('metric', 'metric__metric_unit')  # Add metric_unit to select_related
            
            # Apply the same date filters as the original query
            if date_from:
                records_till_date = records_till_date.filter(player_training__session__date__gte=date_from)
                
            # Group by metric
            for record in records_till_date:
                metric_id = record.metric.id
                if metric_id not in metrics_till_date:
                    metrics_till_date[metric_id] = {
                        'is_lower_better': record.metric.is_lower_better,
                        'name': record.metric.name,
                        'weight': Decimal(str(record.metric.metric_unit.normalization_weight if record.metric.metric_unit else 1.0)),
                        'records': []
                    }
                
                metrics_till_date[metric_id]['records'].append({
                    'date': record.player_training.session.date,
                    'value': record.value
                })
            
            # Calculate weighted improvement for each metric from first to current date
            weighted_normalized_improvements = []
            total_weights = Decimal('0.0')
            
            for metric_id, data in metrics_till_date.items():
                if len(data['records']) < 2:
                    continue  # Skip metrics with insufficient data
                    
                # Sort records chronologically
                sorted_records = sorted(data['records'], key=lambda x: x['date'])
                  # Calculate improvement between first and last record for this date
                first_record = sorted_records[0]
                last_record = sorted_records[-1]
                
                # Use the shared calculation function for consistency
                improvement_data = calculate_normalized_improvement(
                    last_record['value'],
                    first_record['value'],
                    data['is_lower_better'],
                    float(data['weight'])
                )
                
                # Add the normalized percentage to our weighted improvements
                if improvement_data['percentage'] is not None:
                    weighted_normalized_improvements.append(Decimal(str(improvement_data['percentage'])))
                    total_weights += data['weight']
            
            # Only add a data point if we have improvements to average
            if weighted_normalized_improvements and total_weights:
                avg_improvement = sum(weighted_normalized_improvements) / total_weights
                overall_points.append({
                    'date': date,
                    'value': round(float(avg_improvement), 2),  # Convert to float for serialization
                    'notes': f"Average improvement across {len(weighted_normalized_improvements)} metrics",
                    'improvement_from_last': None,
                    'improvement_percentage': None
                })
                
            prev_date = date
            
        return overall_points

    @staticmethod
    def calculate_overall_improvement(player, date_from=None, date_to=None):
        """
        Calculate overall improvement across all metrics for a player
        
        Args:
            player: Player instance
            date_from: Optional start date filter
            date_to: Optional end date filter
            
        Returns:
            Dictionary with overall improvement metrics or None if not enough data
        """
        from decimal import Decimal
        
        # Check if player has any training records at all
        if not hasattr(player, 'training_records') or not player.training_records.exists():
            return None
            
        # Fetch all metrics for this player with date range
        records_query = PlayerMetricRecord.objects.filter(
            player_training__player=player
        ).select_related(
            'player_training__session',
            'metric',
            'metric__metric_unit'  # Add metric_unit to select_related
        )
        
        # Apply date filters if provided
        if date_from:
            records_query = records_query.filter(player_training__session__date__gte=date_from)
        if date_to:
            records_query = records_query.filter(player_training__session__date__lte=date_to)
            
        # Group records by metric
        metrics_data = {}
        for record in records_query:
            metric_id = record.metric.id
            if metric_id not in metrics_data:
                metrics_data[metric_id] = {
                    'is_lower_better': record.metric.is_lower_better,
                    'name': record.metric.name,
                    'weight': Decimal(str(record.metric.metric_unit.normalization_weight if record.metric.metric_unit else 1.0)),
                    'records': []
                }
            
            metrics_data[metric_id]['records'].append({
                'date': record.player_training.session.date,
                'value': record.value
            })
        
        # Calculate weighted improvement percentages for each metric
        weighted_normalized_improvements = []
        total_weights = Decimal('0.0')
        
        for metric_id, data in metrics_data.items():
            if len(data['records']) < 2:
                continue  # Skip metrics with insufficient data
                
            # Sort records chronologically
            sorted_records = sorted(data['records'], key=lambda x: x['date'])
            
            # Calculate improvement between first and last record
            first_record = sorted_records[0]
            last_record = sorted_records[-1]
            
            # Calculate raw improvement
            raw_improvement = last_record['value'] - first_record['value']
            
            # Adjust for metrics where lower is better
            if data['is_lower_better']:
                raw_improvement = -raw_improvement
                
            # Calculate percentage improvement if first value is not zero
            if first_record['value'] != 0:
                raw_percentage = (raw_improvement / abs(first_record['value'])) * Decimal('100')
                weight = data['weight']
                
                # Apply the weight to normalize the percentage
                normalized_percentage = raw_percentage * weight
                weighted_normalized_improvements.append(normalized_percentage)
                total_weights += weight
        
        # Calculate overall improvement as weighted average of all metrics
        if weighted_normalized_improvements and total_weights:
            avg_improvement = sum(weighted_normalized_improvements) / total_weights
            return {
                'percentage': float(avg_improvement),  # Convert to float for serialization
                'metric_count': len(weighted_normalized_improvements),
                'is_positive': avg_improvement > 0
            }
        
        return None

    @staticmethod
    def calculate_recent_improvement(player, date_from=None, date_to=None):
        """
        Calculate improvement in the last 30 days (or specified range) across all metrics
        
        Args:
            player: Player instance
            date_from: Optional start date filter
            date_to: Optional end date filter
            
        Returns:
            Dictionary with recent improvement metrics or None if not enough data
        """
        from decimal import Decimal
        
        # Check if player has any training records at all
        if not hasattr(player, 'training_records') or not player.training_records.exists():
            return None
            
        # Get current date and date 30 days ago
        today = timezone.now().date()
        thirty_days_ago = today - timezone.timedelta(days=30)
        
        # Get query parameters - override 30 days if date_from is provided
        if date_from:
            if isinstance(date_from, str):
                thirty_days_ago = datetime.strptime(date_from, '%Y-%m-%d').date()
            else:
                thirty_days_ago = date_from
        
        if date_to:
            if isinstance(date_to, str):
                today = datetime.strptime(date_to, '%Y-%m-%d').date()
            else:
                today = date_to
        
        # Fetch metrics for last 30 days
        recent_records = PlayerMetricRecord.objects.filter(
            player_training__player=player,
            player_training__session__date__gte=thirty_days_ago,
            player_training__session__date__lte=today
        ).select_related(
            'player_training__session',
            'metric',
            'metric__metric_unit'  # Add metric_unit to select_related
        )
        
        # Group records by metric
        metrics_data = {}
        for record in recent_records:
            metric_id = record.metric.id
            if metric_id not in metrics_data:
                metrics_data[metric_id] = {
                    'is_lower_better': record.metric.is_lower_better,
                    'name': record.metric.name,
                    'weight': Decimal(str(record.metric.metric_unit.normalization_weight if record.metric.metric_unit else 1.0)),
                    'records': []
                }
            
            metrics_data[metric_id]['records'].append({
                'date': record.player_training.session.date,
                'value': record.value
            })
        
        # Calculate weighted improvement percentages for each metric
        weighted_normalized_improvements = []
        total_weights = Decimal('0.0')
        
        for metric_id, data in metrics_data.items():
            if len(data['records']) < 2:
                continue  # Skip metrics with insufficient data
                
            # Sort records chronologically
            sorted_records = sorted(data['records'], key=lambda x: x['date'])
            
            # Calculate improvement between first and last record
            first_record = sorted_records[0]
            last_record = sorted_records[-1]
            
            # Calculate raw improvement
            raw_improvement = last_record['value'] - first_record['value']
            
            # Adjust for metrics where lower is better
            if data['is_lower_better']:
                raw_improvement = -raw_improvement
                
            # Calculate percentage improvement if first value is not zero
            if first_record['value'] != 0:
                raw_percentage = (raw_improvement / abs(first_record['value'])) * Decimal('100')
                weight = data['weight']
                
                # Apply the weight to normalize the percentage
                normalized_percentage = raw_percentage * weight
                weighted_normalized_improvements.append(normalized_percentage)
                total_weights += weight
        
        # Calculate overall improvement as weighted average of all metrics
        if weighted_normalized_improvements and total_weights:
            avg_improvement = sum(weighted_normalized_improvements) / total_weights
            return {
                'percentage': float(avg_improvement),  # Convert to float for serialization
                'metric_count': len(weighted_normalized_improvements),
                'is_positive': avg_improvement > 0
            }
        
        return None

    @staticmethod
    def find_best_performance(player, date_from=None, date_to=None):
        """
        Find best performance in any metric for a player
        
        Args:
            player: Player instance
            date_from: Optional start date filter
            date_to: Optional end date filter
            
        Returns:
            Dictionary with best performance details or None if no records found
        """
        # Check if player has any training records at all
        if not hasattr(player, 'training_records') or not player.training_records.exists():
            return None
            
        # Fetch all metrics for this player with date range
        records_query = PlayerMetricRecord.objects.filter(
            player_training__player=player
        ).select_related(
            'player_training__session',
            'metric',
            'metric__metric_unit'  # Make sure we select_related the metric_unit
        )
        
        # Apply date filters if provided
        if date_from:
            records_query = records_query.filter(player_training__session__date__gte=date_from)
        if date_to:
            records_query = records_query.filter(player_training__session__date__lte=date_to)
            
        if not records_query.exists():
            return None
            
        # Group by metric to find best performance in each
        best_performances = []
        metrics_seen = set()
        
        for record in records_query:
            metric_id = record.metric.id
            if metric_id not in metrics_seen:
                metrics_seen.add(metric_id)
                
                # Query to find the best record for this metric based on is_lower_better
                if record.metric.is_lower_better:
                    best_record = records_query.filter(
                        metric_id=metric_id
                    ).order_by('value').first()
                else:
                    best_record = records_query.filter(
                        metric_id=metric_id
                    ).order_by('-value').first()
                
                if best_record:
                    best_performances.append({
                        'metric_id': metric_id,
                        'metric_name': best_record.metric.name,
                        'value': best_record.value,
                        'unit': best_record.metric.metric_unit.code,  # Use metric_unit.code instead of unit
                        'date': best_record.player_training.session.date,
                        'is_lower_better': best_record.metric.is_lower_better
                    })
        
        # If we found any performances, return the "best" one
        if best_performances:
            # For now, just return the first one
            return best_performances[0]
            
        return None

    @staticmethod
    def count_training_sessions(player, date_from=None, date_to=None):
        """
        Calculate how many unique training sessions the player has attended
        
        Args:
            player: Player instance
            date_from: Optional start date filter
            date_to: Optional end date filter
            
        Returns:
            Number of training sessions attended
        """
        # Check if player has any training records at all
        if not hasattr(player, 'training_records') or not player.training_records.exists():
            return 0
            
        # Fetch all training sessions for this player
        sessions_query = PlayerTraining.objects.filter(
            player=player
        ).values('session').distinct()
        
        # Apply date filters if provided
        if date_from:
            sessions_query = sessions_query.filter(session__date__gte=date_from)
        if date_to:
            sessions_query = sessions_query.filter(session__date__lte=date_to)
            
        return sessions_query.count()
