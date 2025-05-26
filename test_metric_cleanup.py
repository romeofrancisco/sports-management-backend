#!/usr/bin/env python
"""
Test script to verify the metric cleanup functionality
"""
import os
import sys
import django

# Add the project directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')
django.setup()

from django.db import transaction
from trainings.models import TrainingSession, PlayerTraining, TrainingMetric, PlayerMetricRecord, TrainingCategory, MetricUnit
from trainings.services.player_training_service import PlayerTrainingService
from teams.models import Player, Team
from users.models import User
from sports.models import Sport

def test_metric_cleanup():
    """Test the metric cleanup functionality"""
    print("=== Testing Metric Cleanup Functionality ===\n")
    
    try:
        # Create test data (if it doesn't exist)
        print("1. Setting up test data...")
          # Get or create a sport
        sport, _ = Sport.objects.get_or_create(
            name="Test Sport",
            defaults={'scoring_type': 'points'}
        )
        
        # Get or create a team
        team, _ = Team.objects.get_or_create(
            name="Test Team",
            defaults={'sport': sport}
        )
        
        # Get or create a user for the player
        user, _ = User.objects.get_or_create(
            email="testplayer@example.com",
            defaults={
                'first_name': 'Test',
                'last_name': 'Player',
                'role': 'Player'
            }
        )        # Get or create a player
        player, _ = Player.objects.get_or_create(
            user=user,
            defaults={
                'jersey_number': 10,
                'sport': sport,
                'team': team,
                'year_level': 'grade_12',
                'course': 'stem'
            }
        )
        
        # Get or create a training session
        session, _ = TrainingSession.objects.get_or_create(
            title="Test Session",
            defaults={
                'date': '2024-01-01',
                'start_time': '10:00:00',
                'end_time': '12:00:00',
                'location': 'Test Field',
                'team': team
            }
        )
        
        # Get or create player training record
        player_training, _ = PlayerTraining.objects.get_or_create(
            player=player,
            session=session
        )        # Get or create some metrics with required categories and units
        category, _ = TrainingCategory.objects.get_or_create(
            name="Test Category",
            defaults={'description': 'Test training category'}
        )
        
        unit, _ = MetricUnit.objects.get_or_create(
            code="test",
            defaults={'name': 'Test Unit', 'description': 'Test metric unit'}
        )
        
        metric1, _ = TrainingMetric.objects.get_or_create(
            name="Test Speed",
            defaults={
                'description': 'Speed test metric',
                'is_lower_better': True,
                'category': category,
                'metric_unit': unit
            }
        )
        
        metric2, _ = TrainingMetric.objects.get_or_create(
            name="Test Strength",
            defaults={
                'description': 'Strength test metric',
                'is_lower_better': False,
                'category': category,
                'metric_unit': unit
            }
        )
        
        metric3, _ = TrainingMetric.objects.get_or_create(
            name="Test Endurance",
            defaults={
                'description': 'Endurance test metric',
                'is_lower_better': True,
                'category': category,
                'metric_unit': unit
            }
        )
        
        print("✓ Test data created successfully\n")
        
        # Test 1: Assign metrics initially
        print("2. Testing initial metric assignment...")
        initial_metrics = [metric1.id, metric2.id, metric3.id]
        
        result = PlayerTrainingService.assign_metrics_to_player_training(
            player_training, initial_metrics
        )
        
        if result['success']:
            print(f"✓ Successfully assigned {result['count']} metrics")
            print(f"✓ Created {len(result['created_records'])} new records")
            
            # Verify metric records were created
            initial_record_count = PlayerMetricRecord.objects.filter(
                player_training=player_training
            ).count()
            print(f"✓ Database shows {initial_record_count} metric records")
        else:
            print(f"✗ Failed to assign metrics: {result.get('error')}")
            return False
        
        print()
        
        # Test 2: Remove some metrics (simulate unchecking)
        print("3. Testing metric removal (simulating unchecking)...")
        reduced_metrics = [metric1.id, metric2.id]  # Remove metric3
        
        result = PlayerTrainingService.assign_metrics_to_player_training(
            player_training, reduced_metrics
        )
        
        if result['success']:
            print(f"✓ Successfully updated to {result['count']} metrics")
            print(f"✓ Deleted {result['deleted_count']} previous metric records")
            
            # Verify metric records were removed
            final_record_count = PlayerMetricRecord.objects.filter(
                player_training=player_training
            ).count()
            print(f"✓ Database shows {final_record_count} metric records (should be 2)")
            
            # Verify specific metric was removed
            metric3_exists = PlayerMetricRecord.objects.filter(
                player_training=player_training,
                metric=metric3
            ).exists()
            
            if not metric3_exists:
                print("✓ Confirmed: Test Endurance metric record was properly deleted")
            else:
                print("✗ Error: Test Endurance metric record still exists!")
                return False
                
        else:
            print(f"✗ Failed to update metrics: {result.get('error')}")
            return False
        
        print()
        
        # Test 3: Completely remove all metrics
        print("4. Testing complete metric removal...")
        empty_metrics = []
        
        result = PlayerTrainingService.assign_metrics_to_player_training(
            player_training, empty_metrics
        )
        
        if result['success']:
            print(f"✓ Successfully updated to {result['count']} metrics")
            print(f"✓ Deleted {result['deleted_count']} previous metric records")
            
            # Verify all metric records were removed
            final_record_count = PlayerMetricRecord.objects.filter(
                player_training=player_training
            ).count()
            print(f"✓ Database shows {final_record_count} metric records (should be 0)")
            
            if final_record_count == 0:
                print("✓ Confirmed: All metric records properly cleaned up")
            else:
                print("✗ Error: Some metric records still exist!")
                return False
                
        else:
            print(f"✗ Failed to remove all metrics: {result.get('error')}")
            return False
        
        print()
        print("=== ALL TESTS PASSED! ===")
        print("✓ Metric assignment works correctly")
        print("✓ Metric removal works correctly") 
        print("✓ Database cleanup is functioning properly")
        print("✓ Fix for unchecked metrics issue is working!")
        
        return True
        
    except Exception as e:
        print(f"✗ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_metric_cleanup()
    if success:
        print("\n🎉 The fix is working correctly!")
    else:
        print("\n❌ There are still issues that need to be addressed.")
