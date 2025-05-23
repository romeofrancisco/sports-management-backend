from django.db.models import Q
from trainings.models import PlayerMetricRecord, TrainingMetric

class MetricService:
    """Service class for handling metric-related operations"""
    @staticmethod
    def get_player_metric_records(player, metric_id=None, date_from=None, date_to=None):
        """
        Retrieve metric records for a specific player with filtering options
        
        Args:
            player: Player instance
            metric_id: Optional specific metric to filter by
            date_from: Optional start date filter
            date_to: Optional end date filter
            
        Returns:
            QuerySet of PlayerMetricRecord objects
        """
        # Build query with required filters first
        filters = {
            'player_training__player': player
        }
            
        # Add date filters if provided
        if date_from:
            filters['player_training__session__date__gte'] = date_from
        if date_to:
            filters['player_training__session__date__lte'] = date_to
            
        # Add metric filter if specified and not "overall"
        if metric_id and metric_id != "overall":
            filters['metric_id'] = metric_id
        
        # Create query with all filters at once for better optimization
        records_query = PlayerMetricRecord.objects.filter(
            **filters
        ).select_related(
            'player_training__session',
            'metric',
            'metric__metric_unit'  # Add metric_unit to select_related
        ).order_by(
            'player_training__session__date'
        )
            
        return records_query
    
    @staticmethod
    def process_metric_records(records_query):
        """
        Process raw metric records into a structured format grouped by metrics
        
        Args:
            records_query: QuerySet of PlayerMetricRecord objects
            
        Returns:
            Dictionary mapping metric IDs to their processed data
        """
        # Ensure we select_related metric_unit to avoid extra queries
        if not records_query._prefetch_related_lookups:
            records_query = records_query.select_related(
                'player_training__session',
                'metric',
                'metric__metric_unit'
            )
        
        metrics_data = {}
        
        # Process individual metrics
        for record in records_query:
            metric_id = record.metric.id
            if metric_id not in metrics_data:
                metrics_data[metric_id] = {
                    'metric_id': metric_id,
                    'metric_name': record.metric.name,
                    'unit': record.metric.metric_unit.code if record.metric.metric_unit else '-',
                    'is_lower_better': record.metric.is_lower_better,
                    'data_points': []
                }
            metrics_data[metric_id]['data_points'].append({
                'date': record.player_training.session.date,
                'value': record.value,
                'notes': record.notes,
                'improvement_from_last': record.improvement_from_last,
                'improvement_percentage': record.improvement_percentage
            })
        
        return metrics_data
