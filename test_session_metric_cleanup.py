#!/usr/bin/env python
"""
Test script to verify the session-level metric cleanup functionality
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
from trainings.services.training_session_service import TrainingSessionService
from teams.models import Player, Team
from users.models import User
from sports.models import Sport

def test_session_metric_cleanup():
    """Test the session-level metric cleanup functionality"""
    print("=== Testing Session-Level Metric Cleanup Functionality ===\n")
    
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
          # Get or create users and players
        import random
        base_jersey = random.randint(100, 999)  # Use random high numbers to avoid conflicts
        users_data = [
            ('sessionplayer1@test.com', 'Session Player', 'One', base_jersey + 1),
            ('sessionplayer2@test.com', 'Session Player', 'Two', base_jersey + 2),
            ('sessionplayer3@test.com', 'Session Player', 'Three', base_jersey + 3),
        ]
        
        players = []
        for email, first, last, jersey in users_data:
            user, _ = User.objects.get_or_create(
                email=email,
                defaults={
                    'first_name': first,
                    'last_name': last,
                    'role': 'Player'
                }
            )
            
            player, _ = Player.objects.get_or_create(
                user=user,
                defaults={
                    'jersey_number': jersey,
                    'sport': sport,
                    'team': team,
                    'year_level': 'grade_12',
                    'course': 'stem'
                }
            )
            players.append(player)
        
        # Get or create a training session
        session, _ = TrainingSession.objects.get_or_create(
            title="Test Session for Cleanup",
            defaults={
                'date': '2024-01-01',
                'start_time': '10:00:00',
                'end_time': '12:00:00',
                'location': 'Test Field',
                'team': team,
                'training_type': 'team'
            }
        )
        
        # Create player training records for all players
        player_trainings = []
        for player in players:
            pt, _ = PlayerTraining.objects.get_or_create(
                player=player,
                session=session,
                defaults={'attendance_status': 'present'}
            )
            player_trainings.append(pt)
        
        # Get or create some metrics with required categories and units
        category, _ = TrainingCategory.objects.get_or_create(
            name="Test Category",
            defaults={'description': 'Test training category'}
        )
        
        unit, _ = MetricUnit.objects.get_or_create(
            code="test",
            defaults={'name': 'Test Unit', 'description': 'Test metric unit'}
        )
        
        metric1, _ = TrainingMetric.objects.get_or_create(
            name="Session Test Speed",
            defaults={
                'description': 'Speed test metric for session',
                'is_lower_better': True,
                'category': category,
                'metric_unit': unit
            }
        )
        
        metric2, _ = TrainingMetric.objects.get_or_create(
            name="Session Test Strength",
            defaults={
                'description': 'Strength test metric for session',
                'is_lower_better': False,
                'category': category,
                'metric_unit': unit
            }
        )
        
        metric3, _ = TrainingMetric.objects.get_or_create(
            name="Session Test Endurance",
            defaults={
                'description': 'Endurance test metric for session',
                'is_lower_better': True,
                'category': category,
                'metric_unit': unit
            }
        )
        
        print("✓ Test data created successfully")
        print(f"✓ Created session with {len(player_trainings)} player training records\n")
        
        # Test 1: Assign metrics to entire session initially
        print("2. Testing initial session metric assignment...")
        initial_metrics = [metric1.id, metric2.id, metric3.id]
        
        result = TrainingSessionService.assign_metrics_to_session(
            session, initial_metrics
        )
        
        if result['success']:
            print(f"✓ Successfully assigned {result['assigned_count']} metrics to session")
            print(f"✓ Created {result['total_created_records']} new player metric records")
            print(f"✓ Processed {len(result['player_results'])} players")
            
            # Verify metric records were created for all players
            total_record_count = PlayerMetricRecord.objects.filter(
                player_training__session=session
            ).count()
            expected_count = len(player_trainings) * len(initial_metrics)
            print(f"✓ Database shows {total_record_count} metric records (expected {expected_count})")
            
            if total_record_count == expected_count:
                print("✓ Confirmed: All player metric records created correctly")
            else:
                print(f"✗ Error: Expected {expected_count} records but found {total_record_count}")
                return False
        else:
            print(f"✗ Failed to assign metrics: {result.get('error')}")
            return False
        
        print()
        
        # Test 2: Remove some metrics (simulate unchecking in SessionMetricsConfigModal)
        print("3. Testing session metric removal (simulating unchecking)...")
        reduced_metrics = [metric1.id, metric2.id]  # Remove metric3
        
        result = TrainingSessionService.assign_metrics_to_session(
            session, reduced_metrics
        )
        
        if result['success']:
            print(f"✓ Successfully updated session to {result['assigned_count']} metrics")
            print(f"✓ Deleted {result['total_deleted_records']} player metric records")
            print(f"✓ Created {result['total_created_records']} new records")
            
            # Verify metric records were removed for all players
            final_record_count = PlayerMetricRecord.objects.filter(
                player_training__session=session
            ).count()
            expected_count = len(player_trainings) * len(reduced_metrics)
            print(f"✓ Database shows {final_record_count} metric records (expected {expected_count})")
            
            # Verify specific metric was removed for all players
            metric3_exists = PlayerMetricRecord.objects.filter(
                player_training__session=session,
                metric=metric3
            ).exists()
            
            if not metric3_exists:
                print("✓ Confirmed: Session Test Endurance metric records were properly deleted for all players")
            else:
                print("✗ Error: Session Test Endurance metric records still exist!")
                return False
                
            if final_record_count == expected_count:
                print("✓ Confirmed: Correct number of metric records remaining")
            else:
                print(f"✗ Error: Expected {expected_count} records but found {final_record_count}")
                return False
                
        else:
            print(f"✗ Failed to update session metrics: {result.get('error')}")
            return False
        
        print()
        
        # Test 3: Completely remove all metrics from session
        print("4. Testing complete session metric removal...")
        empty_metrics = []
        
        result = TrainingSessionService.assign_metrics_to_session(
            session, empty_metrics
        )
        
        if result['success']:
            print(f"✓ Successfully updated session to {result['assigned_count']} metrics")
            print(f"✓ Deleted {result['total_deleted_records']} player metric records")
            
            # Verify all metric records were removed for all players
            final_record_count = PlayerMetricRecord.objects.filter(
                player_training__session=session
            ).count()
            print(f"✓ Database shows {final_record_count} metric records (should be 0)")
            
            if final_record_count == 0:
                print("✓ Confirmed: All player metric records properly cleaned up from session")
            else:
                print("✗ Error: Some metric records still exist!")
                return False
                
        else:
            print(f"✗ Failed to remove all session metrics: {result.get('error')}")
            return False
        
        print()
        print("=== ALL SESSION TESTS PASSED! ===")
        print("✓ Session metric assignment works correctly")
        print("✓ Session metric removal works correctly") 
        print("✓ Database cleanup is functioning properly for sessions")
        print("✓ SessionMetricsConfigModal unchecked metrics fix is working!")
        print("✓ All players in session get metrics removed properly")
        
        return True
        
    except Exception as e:
        print(f"✗ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_session_metric_cleanup()
    if success:
        print("\n🎉 The session-level fix is working correctly!")
        print("✅ SessionMetricsConfigModal will now properly remove unchecked metrics from all players!")
    else:
        print("\n❌ There are still issues that need to be addressed.")
