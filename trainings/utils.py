from django.core.cache import cache
from functools import wraps
import hashlib
import json
import time
from decimal import Decimal


def calculate_normalized_improvement(current_value, previous_value, is_lower_better, normalization_weight=1.0):
    """
    Calculate improvement percentage with normalization weight applied.
    
    This function consolidates the improvement calculation logic used across
    ProgressService and multi-player utilities to ensure consistency.
    
    Args:
        current_value: Current metric value
        previous_value: Previous metric value to compare against
        is_lower_better: Whether lower values indicate better performance
        normalization_weight: Weight to apply for normalization (default 1.0)
        
    Returns:
        dict: Contains percentage and raw improvement values
    """
    # Convert to Decimal for precise calculation
    current_val = Decimal(str(current_value))
    prev_val = Decimal(str(previous_value))
    
    # Calculate raw improvement
    raw_improvement = current_val - prev_val
    
    # Adjust for metrics where lower is better
    if is_lower_better:
        raw_improvement = -raw_improvement
    
    # Calculate percentage improvement if previous value is not zero
    if prev_val != 0:
        raw_percentage = (raw_improvement / abs(prev_val)) * Decimal('100')
        
        # Apply normalization weight
        weight = Decimal(str(normalization_weight))
        normalized_percentage = raw_percentage * weight
        
        return {
            'percentage': float(normalized_percentage),
            'raw_value': float(raw_improvement),
            'is_positive': raw_improvement > 0
        }
    else:
        return {
            'percentage': 0.0,
            'raw_value': float(raw_improvement),
            'is_positive': raw_improvement > 0
        }

def cached_db_query(timeout=300):
    """
    Cache decorator for expensive database queries.
    
    Args:
        timeout: Cache timeout in seconds (default 5 minutes)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create a unique cache key based on function name and arguments
            cache_key_parts = [
                func.__module__,
                func.__name__,
                str(args),
                str(sorted(kwargs.items()))
            ]
            cache_key = hashlib.md5(json.dumps(cache_key_parts).encode()).hexdigest()
            
            # Try to get data from cache
            cached_result = cache.get(cache_key)
            
            if cached_result is not None:
                return cached_result
            
            # Cache miss, execute the original function
            result = func(*args, **kwargs)
            
            # Store the result in cache
            cache.set(cache_key, result, timeout)
            
            return result
        return wrapper
    return decorator


def batch_fetch_record_data(player_ids, metric_id, date_from=None, date_to=None):
    """
    Optimized batch fetching of player metric records data.
    
    Args:
        player_ids: List of player IDs
        metric_id: Metric ID to filter by (can be 'overall' for overall performance)
        date_from: Optional date range start
        date_to: Optional date range end
        
    Returns:
        Dictionary mapping player_ids to their records data
    """
    from django.db.models import F
    from django.db.models.functions import Coalesce
    from trainings.models import PlayerMetricRecord
    from trainings.services.progress_service import ProgressService
      # Special handling for 'overall' metric
    if metric_id == 'overall':
        records_by_player = {}
        for player_id in player_ids:
            # Get player object for ProgressService
            from teams.models import Player
            try:
                player = Player.objects.get(user_id=player_id)
                # Get necessary records for overall calculation
                records_query = PlayerMetricRecord.objects.filter(
                    player_training__player=player
                ).select_related(
                    'player_training__session',
                    'metric'
                )
                
                # Apply date filters if provided
                if date_from:
                    records_query = records_query.filter(player_training__session__date__gte=date_from)                
                if date_to:
                    records_query = records_query.filter(player_training__session__date__lte=date_to)
                
                # Create overall metric data structure using ProgressService
                overall_points = ProgressService.calculate_overall_data_points(player, records_query, date_from, date_to)
                
                if overall_points:
                    # Make sure each data point has the is_lower_better field set to False
                    # because overall performance is always "higher is better"
                    for point in overall_points:
                        point['is_lower_better'] = False
                    
                    # Get the overall improvement calculation for consistency
                    overall_improvement = ProgressService.calculate_overall_improvement(player, date_from, date_to)
                    if overall_improvement and len(overall_points) >= 2:
                        # Add the consistent overall improvement percentage to the last data point
                        # This ensures the calculation in calculate_player_improvement will match ProgressService
                        overall_points[-1]['value'] = overall_improvement['percentage']
                    
                    records_by_player[player_id] = overall_points
                else:
                    records_by_player[player_id] = []
            except Player.DoesNotExist:
                records_by_player[player_id] = []
                
        return records_by_player
      # Regular metrics processing
    # Start with a base query for all specified players and the given metric
    base_query = PlayerMetricRecord.objects.filter(
        player_training__player__user_id__in=player_ids,
        metric_id=metric_id
    ).select_related(
        'player_training__player',
        'player_training__session',
        'metric',
        'metric__metric_unit'  # Add metric_unit to get normalization weights
    )
    
    # Apply date filters if provided
    if date_from:
        base_query = base_query.filter(player_training__session__date__gte=date_from)
    if date_to:
        base_query = base_query.filter(player_training__session__date__lte=date_to)
    
    # Organize the records by player for efficient processing
    records_by_player = {}
    
    # Execute query with all necessary related fields to avoid N+1 queries
    records = base_query.order_by(
        'player_training__player__user_id', 
        'player_training__session__date'
    )
      # Group results by player
    for record in records:
        player_id = record.player_training.player.user_id
        if player_id not in records_by_player:
            records_by_player[player_id] = []
            
        records_by_player[player_id].append({
            'date': record.player_training.session.date,
            'value': record.value,
            'notes': record.notes,
            'session_id': record.player_training.session.session_id,
            'is_lower_better': record.metric.is_lower_better,
            'normalization_weight': float(record.metric.metric_unit.normalization_weight) if record.metric.metric_unit else 1.0
        })
    
    # Process improvements for each player's records
    for player_id, records in records_by_player.items():
        # Sort chronologically to ensure proper improvement calculation
        records.sort(key=lambda x: x['date'])
          # Calculate improvements
        for i, record in enumerate(records):
            if i > 0:
                prev_record = records[i-1]
                current_value = float(record['value'])
                prev_value = float(prev_record['value'])
                
                # Use the new shared calculation function with normalization weights
                improvement_data = calculate_normalized_improvement(
                    current_value,
                    prev_value,
                    record['is_lower_better'],
                    record['normalization_weight']
                )
                
                record['improvement_from_last'] = improvement_data['raw_value']
                record['improvement_percentage'] = improvement_data['percentage']
            else:
                # First record has no previous to compare with
                record['improvement_from_last'] = None
                record['improvement_percentage'] = None
    
    return records_by_player


def calculate_player_improvement(records_by_player, metric_is_lower_better=False, metric_id=None):
    """
    Calculate overall improvement metrics for multiple players.
    
    Args:
        records_by_player: Dictionary of player records as returned by batch_fetch_record_data
        metric_is_lower_better: Whether lower values are better for this metric
        metric_id: The metric ID being processed, needed for special handling of "overall" metric
        
    Returns:
        Dictionary mapping player_ids to their overall improvement stats
    """
    improvements = {}
    
    # Special handling for "overall" metric to match the calculation in ProgressService
    is_overall_metric = metric_id == "overall"
    
    for player_id, records in records_by_player.items():
        if len(records) < 2:
            # Skip players with insufficient data
            improvements[player_id] = {
                'overall_improvement': None,
                'recent_improvement': None,
                'best_performance': None
            }
            continue
        
        # Sort chronologically
        sorted_records = sorted(records, key=lambda x: x['date'])
        
        # Calculate overall improvement (first to last)
        first_record = sorted_records[0]
        last_record = sorted_records[-1]
        
        first_value = float(first_record['value'])
        last_value = float(last_record['value'])
        
        # Check if the record itself has is_lower_better (for overall metric)
        # otherwise use the passed in parameter
        record_is_lower_better = first_record.get('is_lower_better', metric_is_lower_better)
        
        # Get normalization weight for consistent calculation
        normalization_weight = first_record.get('normalization_weight', 1.0)
        
        # For overall metric, we need to correct the percentage to match the calculation in ProgressService
        if is_overall_metric:
            # When it's the "overall" metric, we need to make sure to use the consistent calculation
            # The value we got is likely the average of improvement percentages across multiple metrics
            # So for consistency with ProgressService.calculate_overall_improvement(), we use that value directly
            # But make sure we properly respect the is_positive flag based on the value's sign
            overall_percentage = last_value
            # Update is_positive flag to be consistent with the percentage value
            overall_improvement = 1 if last_value > 0 else -1
        else:
            # Use the shared calculation function with normalization weights
            improvement_data = calculate_normalized_improvement(
                last_value,
                first_value,
                record_is_lower_better,
                normalization_weight
            )
            overall_percentage = improvement_data['percentage']
            overall_improvement = improvement_data['raw_value']
        
        # Calculate recent improvement (using last 30% of records or at least 2)
        recent_count = max(2, int(len(sorted_records) * 0.3))
        recent_records = sorted_records[-recent_count:]
        
        if len(recent_records) >= 2:
            recent_first = recent_records[0]
            recent_last = recent_records[-1]
            
            recent_first_value = float(recent_first['value'])
            recent_last_value = float(recent_last['value'])
            
            # Get normalization weight and is_lower_better from record
            recent_record_is_lower_better = recent_first.get('is_lower_better', metric_is_lower_better)
            recent_normalization_weight = recent_first.get('normalization_weight', 1.0)
            
            # For overall metric, special handling to be consistent with other views
            if is_overall_metric:
                # For the overall metric, recent improvement should simply be the difference of percentages
                # And the is_positive flag should be directly based on the sign of that difference
                recent_improvement = recent_last_value - recent_first_value
                recent_percentage = recent_improvement  # Already a percentage for overall metric
                recent_improvement = 1 if recent_percentage > 0 else -1
            else:
                # Use the shared calculation function with normalization weights
                recent_improvement_data = calculate_normalized_improvement(
                    recent_last_value,
                    recent_first_value,
                    recent_record_is_lower_better,
                    recent_normalization_weight
                )
                recent_percentage = recent_improvement_data['percentage']
                recent_improvement = recent_improvement_data['raw_value']
        else:
            recent_improvement = None
            recent_percentage = None
        
        # Find best performance
        if metric_is_lower_better:
            # For metrics where lower is better (like time), find minimum
            best_record = min(sorted_records, key=lambda x: float(x['value']))
        else:
            # For metrics where higher is better, find maximum
            best_record = max(sorted_records, key=lambda x: float(x['value']))
            
        improvements[player_id] = {
            'overall_improvement': {
                'percentage': overall_percentage,
                'raw_value': overall_improvement,
                'is_positive': overall_improvement > 0 if not is_overall_metric else overall_percentage > 0
            },
            'recent_improvement': {
                'percentage': recent_percentage,
                'raw_value': recent_improvement,
                'is_positive': recent_percentage > 0 if is_overall_metric else (recent_improvement > 0 if recent_improvement is not None else None)
            },
            'best_performance': {
                'value': best_record['value'],
                'date': best_record['date']
            }
        }
    
    return improvements
