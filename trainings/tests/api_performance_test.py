"""
Performance Testing Script for Player Progress ViewSet
This script will measure the performance of the optimized multi_player action.
"""
import os
import django
import time
import statistics
import random
import requests
from datetime import datetime, timedelta

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')
django.setup()

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from trainings.models import Player, Team, TrainingMetric

User = get_user_model()

def format_time(time_ms):
    """Format milliseconds to a readable string"""
    if time_ms < 1000:
        return f"{time_ms:.2f}ms"
    else:
        return f"{time_ms/1000:.2f}s"

def test_multi_player_performance(team_slug=None, metric_id=None, num_runs=5, player_limit=None, use_cache=True):
    """Test the performance of the multi_player endpoint"""
    print("\n" + "="*80)
    print(f"PERFORMANCE TEST: multi_player API - Running {num_runs} tests")
    print("="*80)
    
    # Set up test client
    client = APIClient()
    
    # Get or create a test user
    admin_user, _ = User.objects.get_or_create(
        email='admin@test.com',
        defaults={
            'first_name': 'Admin',
            'last_name': 'User',
            'is_staff': True,
            'is_superuser': True
        }
    )
    admin_user.set_password('password123')
    admin_user.save()
    
    # Authenticate the client
    client.force_authenticate(user=admin_user)
    
    # If no team slug provided, use the first available team
    if not team_slug:
        team = Team.objects.first()
        if not team:
            print("No teams found in the database. Please create a team first.")
            return
        team_slug = team.slug
    
    # If no metric ID provided, use the first available metric
    if not metric_id:
        metric = TrainingMetric.objects.first()
        if not metric:
            print("No metrics found in the database. Please create a metric first.")
            return
        metric_id = metric.id
    
    # Get players for this team
    players = Player.objects.filter(team__slug=team_slug)
    if player_limit:
        players = players[:player_limit]
    
    player_ids = ','.join(str(p.user_id) for p in players)
    
    # Prepare URL
    params = {
        'team': team_slug,
        'metric_id': metric_id,
        'no_cache': 'true' if not use_cache else 'false'
    }
    
    # Define test scenarios
    scenarios = [
        {
            'name': 'All players, all dates',
            'params': {**params},
        },
        {
            'name': 'Latest records only',
            'params': {**params, 'latest_only': 'true'},
        },
        {
            'name': 'Last 30 days',
            'params': {
                **params, 
                'date_from': (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            },
        },
        {
            'name': 'Paginated (10 players per page)',
            'params': {**params, 'page_size': '10', 'page': '1'},
        },
        {
            'name': 'Limited data points (5 per player)',
            'params': {**params, 'limit': '5'},
        }
    ]
    
    # Run tests for each scenario
    for scenario in scenarios:
        print(f"\nTesting scenario: {scenario['name']}")
        print("-" * 60)
        
        execution_times = []
        data_points_processed = []
        
        # First request might be slower due to DB connection setup, etc.
        print("Warming up...")
        response = client.get('/api/trainings/player-progress/multi_player/', scenario['params'])
        
        # Run the actual test
        for i in range(num_runs):
            start_time = time.time()
            response = client.get('/api/trainings/player-progress/multi_player/', scenario['params'])
            end_time = time.time()
            
            if response.status_code != 200:
                print(f"Error: {response.status_code} - {response.data}")
                continue
                
            execution_time = (end_time - start_time) * 1000  # Convert to ms
            
            # Check if performance data is in the response
            if 'performance' in response.data:
                server_time = response.data['performance'].get('execution_time_ms', 0)
                data_points = response.data['performance'].get('data_points_count', 0)
                cache_hit = response.data['performance'].get('cache_hit', False)
                
                cache_status = "Cache HIT" if cache_hit else "Cache MISS"
                print(f"Run {i+1}: Server time: {format_time(server_time)}, " 
                      f"Total time: {format_time(execution_time)}, "
                      f"Data points: {data_points}, {cache_status}")
                
                execution_times.append(execution_time)
                data_points_processed.append(data_points)
            else:
                print(f"Run {i+1}: Total time: {format_time(execution_time)}")
                execution_times.append(execution_time)
        
        # Calculate statistics
        if execution_times:
            avg_time = statistics.mean(execution_times)
            median_time = statistics.median(execution_times)
            min_time = min(execution_times)
            max_time = max(execution_times)
            
            print("\nPerformance Summary:")
            print(f"Average response time: {format_time(avg_time)}")
            print(f"Median response time: {format_time(median_time)}")
            print(f"Min response time: {format_time(min_time)}")
            print(f"Max response time: {format_time(max_time)}")
            
            if data_points_processed:
                avg_points = statistics.mean(data_points_processed)
                print(f"Average data points processed: {avg_points:.1f}")
    
    print("\n" + "="*80)
    print("Performance test completed")
    print("="*80)

if __name__ == "__main__":
    # Run the performance test
    test_multi_player_performance(
        team_slug=None,  # Use first available team
        metric_id=None,  # Use first available metric
        num_runs=5,      # Number of test runs per scenario
        player_limit=20, # Limit number of players to test with
        use_cache=True   # Enable caching
    )
