#!/usr/bin/env python
"""
Script to verify the optimizations for the multi_player action in PlayerProgressViewSet
This script can be run to directly check the improvements in performance.
"""
import os
import sys
import django
import time
import datetime
import random
import json
from decimal import Decimal

# Set up Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')
django.setup()

from django.utils import timezone
from django.db import connection
from django.db.models import Count, Avg, Max, Min
from trainings.models import Player, TrainingMetric, PlayerMetricRecord, PlayerTraining, TrainingSession
from trainings.utils import batch_fetch_record_data, calculate_player_improvement

def time_execution(func):
    """Simple decorator to time the execution of a function"""
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        print(f"Execution time: {(end_time - start_time) * 1000:.2f} ms")
        return result
    return wrapper

@time_execution
def get_player_metrics_old_way(team_slug, metric_id, date_from=None, date_to=None, player_ids=None, limit=None):
    """Implementation similar to the original (unoptimized) version"""
    # Get players
    players_query = Player.objects.filter(team__slug=team_slug)
    if player_ids:
        players_query = players_query.filter(user_id__in=player_ids)
    
    players_query = players_query.select_related('team', 'user')
    
    # Get metric
    metric = TrainingMetric.objects.get(id=metric_id)
    
    # Process each player
    results = {}
    
    for player in players_query:
        # Get records for this player
        records_query = PlayerMetricRecord.objects.filter(
            player_training__player=player,
            metric=metric
        ).order_by('player_training__session__date')
        
        # Apply date filters
        if date_from:
            records_query = records_query.filter(player_training__session__date__gte=date_from)
        if date_to:
            records_query = records_query.filter(player_training__session__date__lte=date_to)
        
        # Apply limit
        if limit:
            records_query = records_query[:limit]
        
        # Process records
        data_points = []
        prev_value = None
        
        for record in records_query:
            data_point = {
                'date': record.player_training.session.date,
                'value': record.value,
                'notes': record.notes or "",
                'improvement_from_last': None,
                'improvement_percentage': None
            }
            
            # Calculate improvement if not the first record
            if prev_value is not None:
                current_value = float(record.value)
                improvement = current_value - prev_value
                
                # Adjust sign based on whether lower is better
                if metric.is_lower_better:
                    improvement = -improvement
                    
                # Calculate percentage
                if prev_value != 0:
                    improvement_percentage = (improvement / abs(prev_value)) * 100
                else:
                    improvement_percentage = 0
                    
                data_point['improvement_from_last'] = improvement
                data_point['improvement_percentage'] = improvement_percentage
                
            data_points.append(data_point)
            prev_value = float(record.value)
        
        # Add to results
        results[player.user_id] = {
            'user_id': player.user_id,
            'player_name': player.user.get_full_name(),
            'team': player.team_id,
            'team_slug': player.team.slug,
            'metrics_data': [{
                'metric_id': metric.id,
                'metric_name': metric.name,
                'unit': metric.unit,
                'is_lower_better': metric.is_lower_better,
                'data_points': data_points
            }]
        }
    
    return results

@time_execution
def get_player_metrics_new_way(team_slug, metric_id, date_from=None, date_to=None, player_ids=None, limit=None):
    """Implementation using the optimized batch fetching approach"""
    # Get players with minimal fields
    players_query = Player.objects.filter(team__slug=team_slug)
    if player_ids:
        players_query = players_query.filter(user_id__in=player_ids)
    
    players_query = players_query.select_related('team', 'user').only(
        'user_id', 'team_id', 'team__name', 'team__slug', 'user__first_name', 'user__last_name'
    )
    
    # Get metric info with minimal fields
    metric = TrainingMetric.objects.only('name', 'unit', 'is_lower_better').get(id=metric_id)
    
    # Prepare basic player info
    results = {}
    selected_player_ids = []
    
    for player in players_query:
        player_id = player.user_id
        selected_player_ids.append(player_id)
        
        results[player_id] = {
            'user_id': player_id,
            'player_name': player.user.get_full_name(),
            'team': player.team_id,
            'team_slug': player.team.slug,
            'team_name': player.team.name,
            'metrics_data': []
        }
    
    # Use the batch fetching utility
    records_by_player = batch_fetch_record_data(
        selected_player_ids,
        metric_id,
        date_from,
        date_to
    )
    
    # Calculate improvements
    player_improvements = calculate_player_improvement(
        records_by_player,
        metric.is_lower_better
    )
    
    # Apply limit if specified
    if limit:
        for player_id in records_by_player:
            records_by_player[player_id] = records_by_player[player_id][-limit:]
    
    # Build the final data structure
    for player_id, records in records_by_player.items():
        if player_id in results:
            # Create metric data
            metric_data = {
                'metric_id': int(metric_id),
                'metric_name': metric.name,
                'unit': metric.unit,
                'is_lower_better': metric.is_lower_better,
                'data_points': records
            }
            
            # Add to player's metrics
            results[player_id]['metrics_data'] = [metric_data]
            
            # Add improvement metrics if available
            if player_id in player_improvements:
                improvement_data = player_improvements[player_id]
                
                results[player_id].update({
                    'overall_improvement': improvement_data['overall_improvement'],
                    'recent_improvement': improvement_data['recent_improvement'],
                    'best_performance': improvement_data['best_performance'],
                    'training_count': len(records)
                })
    
    return results

def run_comparison_tests():
    """Run tests comparing the old and new implementations"""
    print("\n" + "="*50)
    print("PERFORMANCE COMPARISON TEST")
    print("="*50)
    
    # Get the first team in the database
    team = Player.objects.values('team__slug').first()
    if not team:
        print("No teams with players found in the database.")
        return
    
    team_slug = team['team__slug']
    
    # Get the first metric in the database
    metric = TrainingMetric.objects.first()
    if not metric:
        print("No metrics found in the database.")
        return
    
    metric_id = metric.id
    
    print(f"Testing with team: {team_slug}, metric: {metric_id}")
    
    # Test 1: All players, all dates
    print("\nTest 1: All players, all dates")
    print("-" * 40)
    
    print("Old implementation:")
    old_results = get_player_metrics_old_way(team_slug, metric_id)
    
    print("\nNew optimized implementation:")
    new_results = get_player_metrics_new_way(team_slug, metric_id)
    
    # Test 2: Limited data points
    print("\nTest 2: Limited to 5 most recent data points per player")
    print("-" * 40)
    
    print("Old implementation:")
    old_results_limited = get_player_metrics_old_way(team_slug, metric_id, limit=5)
    
    print("\nNew optimized implementation:")
    new_results_limited = get_player_metrics_new_way(team_slug, metric_id, limit=5)
    
    # Test 3: Date range filtering
    print("\nTest 3: Last 30 days only")
    print("-" * 40)
    
    date_from = (timezone.now() - datetime.timedelta(days=30)).date()
    
    print("Old implementation:")
    old_results_date_range = get_player_metrics_old_way(team_slug, metric_id, date_from=date_from)
    
    print("\nNew optimized implementation:")
    new_results_date_range = get_player_metrics_new_way(team_slug, metric_id, date_from=date_from)
      # Test 4: Database queries count
    print("\nTest 4: Database query count")
    print("-" * 40)
    
    # Reset query count
    connection.queries_log.clear()
    connection.force_debug_cursor = True
    
    print("Old implementation query count:")
    old_results = get_player_metrics_old_way(team_slug, metric_id)
    old_query_count = len(connection.queries)
    
    # Reset query count
    connection.queries_log.clear()
    
    print("New optimized implementation query count:")
    new_results = get_player_metrics_new_way(team_slug, metric_id)
    new_query_count = len(connection.queries)
    
    # Turn debug cursor off
    connection.force_debug_cursor = False
    
    print(f"\nQuery count comparison:")
    print(f"Old implementation: {old_query_count} queries")
    print(f"New implementation: {new_query_count} queries")
    print(f"Reduction: {old_query_count - new_query_count} queries ({100 * (old_query_count - new_query_count) / old_query_count if old_query_count > 0 else 0:.2f}%)")
    
    print("\n" + "="*50)
    print("Performance test completed")
    print("="*50)

if __name__ == "__main__":
    # Run the tests
    run_comparison_tests()
