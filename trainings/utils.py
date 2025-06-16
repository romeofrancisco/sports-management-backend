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
                player = Player.objects.get(user_id=player_id)                # Get necessary records for overall calculation
                records_query = PlayerMetricRecord.objects.filter(
                    player_training__player=player,
                    value__isnull=False  # Only include records with actual values
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
      # Regular metrics processing    # Start with a base query for all specified players and the given metric
    base_query = PlayerMetricRecord.objects.filter(
        player_training__player__user_id__in=player_ids,
        metric_id=metric_id,
        value__isnull=False  # Only include records with actual values
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
        
        # Check for null values
        if first_record['value'] is None or last_record['value'] is None:
            improvements[player_id] = {
                'overall_improvement': None,
                'recent_improvement': None,
                'best_performance': None
            }
            continue
        
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
            
            # Check for null values in recent records
            if recent_first['value'] is None or recent_last['value'] is None:
                recent_improvement = None
                recent_percentage = None
            else:
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
          # Find best performance (filter out null values first)
        valid_records = [r for r in sorted_records if r['value'] is not None]
        if valid_records:
            if metric_is_lower_better:
                # For metrics where lower is better (like time), find minimum
                best_record = min(valid_records, key=lambda x: float(x['value']))
            else:
                # For metrics where higher is better, find maximum
                best_record = max(valid_records, key=lambda x: float(x['value']))
            
            best_performance = {
                'value': best_record['value'],
                'date': best_record['date']
            }
        else:
            best_performance = None
            
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
            },            'best_performance': best_performance
        }
    
    return improvements


def calculate_best_category(categories_data):
    """
    Calculate the best performing training category for a player based on improvement metrics.
    
    Args:
        categories_data: List of category dictionaries containing 'average_improvement' values
                        (as returned by player_radar_chart endpoint)
        
    Returns:
        dict: The category with the highest average improvement, or None if no categories provided
        
    Example:
        categories = [
            {'category_name': 'Strength', 'average_improvement': 15.5},
            {'category_name': 'Speed', 'average_improvement': 22.3},
            {'category_name': 'Endurance', 'average_improvement': 8.7}
        ]
        best = calculate_best_category(categories)
        # Returns: {'category_name': 'Speed', 'average_improvement': 22.3}
    """
    if not categories_data:
        return None
    
    # Filter out categories with no improvement data
    valid_categories = [
        category for category in categories_data 
        if 'average_improvement' in category and category['average_improvement'] is not None
    ]
    
    if not valid_categories:
        return None
    
    # Find the category with the highest average improvement
    best_category = max(valid_categories, key=lambda x: x['average_improvement'])
    
    return best_category


def calculate_best_category_for_player(player_id, date_from=None, date_to=None):
    """
    Calculate the best performing training category for a specific player.
    
    This function uses the same logic as the player_radar_chart endpoint to ensure consistency.
    
    Args:
        player_id: ID of the player
        date_from: Optional start date filter (YYYY-MM-DD format)
        date_to: Optional end date filter (YYYY-MM-DD format)
        
    Returns:
        dict: Contains best_category info and summary statistics, or None if no data
        
    Example:
        result = calculate_best_category_for_player(123, '2024-01-01', '2024-12-31')
        # Returns:
        # {
        #     'best_category': {
        #         'category_id': 2,
        #         'category_name': 'Speed',
        #         'average_improvement': 22.3,
        #         'performance_score': 75.2
        #     },
        #     'summary': {
        #         'categories_analyzed': 5,
        #         'overall_improvement': 14.2
        #     }
        # }
    """
    from django.db.models import Avg, Max, Min, Count
    from decimal import Decimal
    from django.utils.dateparse import parse_date
    from teams.models import Player
    from trainings.models import TrainingCategory, TrainingMetric, PlayerMetricRecord
    
    try:
        player = Player.objects.get(user_id=player_id)
    except Player.DoesNotExist:
        return None
    
    # Build base query for player's metric records
    records_query = PlayerMetricRecord.objects.filter(
        player_training__player=player
    ).select_related(
        'metric__category',
        'metric__metric_unit',
        'player_training__session'
    )
    
    # Apply date filters if provided
    if date_from:
        try:
            date_from_parsed = parse_date(date_from)
            records_query = records_query.filter(
                player_training__session__date__gte=date_from_parsed
            )
        except (ValueError, TypeError):
            return None
    
    if date_to:
        try:
            date_to_parsed = parse_date(date_to)
            records_query = records_query.filter(
                player_training__session__date__lte=date_to_parsed
            )
        except (ValueError, TypeError):
            return None
    
    # Get all training categories with metrics for this player
    categories_with_data = []
    categories = TrainingCategory.objects.filter(
        metrics__records__player_training__player=player
    ).distinct()
    
    for category in categories:
        # Get all records for metrics in this category
        category_records = records_query.filter(
            metric__category=category
        ).order_by('player_training__session__date')
        
        if not category_records.exists():
            continue
        
        # Calculate performance metrics for this category
        metrics_in_category = TrainingMetric.objects.filter(
            category=category,
            records__player_training__player=player
        ).distinct()
        
        total_improvement = 0
        metrics_with_improvement = 0
        latest_performance_score = 0
        
        for metric in metrics_in_category:
            metric_records = category_records.filter(metric=metric)
            
            if metric_records.count() < 2:
                continue
            
            # Get first and latest records for improvement calculation
            first_record = metric_records.first()
            latest_record = metric_records.last()
            
            first_value = float(first_record.value)
            latest_value = float(latest_record.value)
            
            # Calculate improvement percentage
            if first_value != 0:
                raw_improvement = ((latest_value - first_value) / first_value) * 100
                
                # Apply normalization and direction logic
                normalization_weight = 1.0
                if metric.metric_unit:
                    normalization_weight = float(metric.metric_unit.normalization_weight)
                
                improvement = raw_improvement * normalization_weight
                
                # For metrics where lower is better, invert the improvement
                if metric.is_lower_better:
                    improvement = -improvement
                
                total_improvement += improvement
                metrics_with_improvement += 1
                
                # Calculate latest performance score (0-100 scale)
                performance_score = max(0, min(100, 50 + (improvement / 2)))
                latest_performance_score += performance_score
        
        # Calculate category averages
        avg_improvement = (total_improvement / metrics_with_improvement) if metrics_with_improvement > 0 else 0
        avg_performance_score = (latest_performance_score / metrics_with_improvement) if metrics_with_improvement > 0 else 50
        
        categories_with_data.append({
            'category_id': category.id,
            'category_name': category.name,
            'description': category.description,
            'average_improvement': round(avg_improvement, 2),
            'performance_score': round(avg_performance_score, 2),
            'metrics_count': metrics_with_improvement,
            'total_records': category_records.count()
        })
    
    if not categories_with_data:
        return None
    
    # Calculate the best category
    best_category = calculate_best_category(categories_with_data)
    
    if not best_category:
        return None
    
    # Calculate summary statistics
    overall_improvement = sum(cat['average_improvement'] for cat in categories_with_data) / len(categories_with_data)
    
    return {
        'best_category': best_category,
        'summary': {
            'categories_analyzed': len(categories_with_data),
            'overall_improvement': round(overall_improvement, 2),
            'total_metrics': sum(cat['metrics_count'] for cat in categories_with_data)
        },
        'all_categories': categories_with_data
    }
