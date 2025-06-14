#!/usr/bin/env python
"""
Test script to verify that metric assignment doesn't create placeholder records with value 0
"""
import os
import sys
import django
from datetime import datetime, timedelta
import uuid

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')
django.setup()

from django.test import TestCase
from trainings.models import TrainingSession, PlayerTraining, TrainingMetric, PlayerMetricRecord, TrainingCategory, MetricUnit
from trainings.services.player_training_service import PlayerTrainingService
from teams.models import Player, Team, Coach
from users.models import User
from django.utils import timezone

def test_metric_assignment():
    """Test that newly assigned metrics don't create placeholder records with value 0"""
    
    print("🧪 Testing metric assignment behavior...")
    
    # Generate unique identifiers to avoid conflicts
    test_id = str(uuid.uuid4())[:8]
    
    # Clean up any existing test data first
    print("🧹 Cleaning up any existing test data...")
    try:
        # Clean up test users and related data
        test_users = User.objects.filter(email__startswith="test_coach_", email__endswith="@test.com")
        for user in test_users:
            if hasattr(user, 'coach_profile'):
                user.coach_profile.delete()
            if hasattr(user, 'player_profile'):
                user.player_profile.delete()
            user.delete()
        
        # Clean up test teams
        Team.objects.filter(name__startswith="Test Team").delete()
    except Exception as e:
        print(f"⚠️  Cleanup warning: {e}")
    
    # Create test data
    print("📝 Creating test data...")
    
    try:
        # Create coach user
        coach_user = User.objects.create_user(
            email=f"test_coach_{test_id}@test.com",
            password="testpass123",
            first_name="Test",
            last_name="Coach"
        )
        
        # Create team
        team = Team.objects.create(
            name=f"Test Team {test_id}"
        )
        
        # Create coach profile
        coach = Coach.objects.create(
            user=coach_user,
            contact_number="1234567890"
        )
        coach.teams.add(team)
        
        # Create player user
        player_user = User.objects.create_user(
            email=f"test_player_{test_id}@test.com",
            password="testpass123",
            first_name="Test",
            last_name="Player"
        )
        
        # Create player profile
        player = Player.objects.create(
            user=player_user,
            team=team,
            jersey_number=10,
            position="PG"
        )
        
        # Create training session
        session = TrainingSession.objects.create(
            title=f"Test Session {test_id}",
            date=timezone.now().date(),
            start_time=timezone.now().time(),
            end_time=(timezone.now() + timedelta(hours=2)).time(),
            team=team,
            coach=coach
        )
        
        # Create player training record
        player_training = PlayerTraining.objects.create(
            player=player,
            session=session,
            attendance_status='present'
        )
        
        # Get or create metric unit and category
        metric_unit, _ = MetricUnit.objects.get_or_create(
            name="Repetitions",
            defaults={
                "code": "reps",
                "description": "Number of repetitions"
            }
        )
        
        category, _ = TrainingCategory.objects.get_or_create(
            name="Strength",
            defaults={
                "description": "Strength training metrics"
            }
        )
        
        # Create training metrics
        metric1 = TrainingMetric.objects.create(
            name=f"Push-ups {test_id}",
            description="Number of push-ups completed",
            metric_unit=metric_unit,
            category=category,
            is_lower_better=False
        )
        
        metric2 = TrainingMetric.objects.create(
            name=f"Sit-ups {test_id}",
            description="Number of sit-ups completed",
            metric_unit=metric_unit,
            category=category,
            is_lower_better=False
        )
        
        print("✅ Test data created successfully")
        
        # Test 1: Check initial state (no metric records)
        initial_record_count = PlayerMetricRecord.objects.filter(player_training=player_training).count()
        print(f"📊 Initial PlayerMetricRecord count: {initial_record_count}")
        
        # Test 2: Assign metrics to player
        print("🔧 Assigning metrics to player...")
        result = PlayerTrainingService.assign_metrics_to_player_training(
            player_training, 
            [metric1.id, metric2.id]
        )
        
        print(f"📋 Assignment result: {result}")
        
        # Test 3: Check that no PlayerMetricRecord instances were created
        after_assignment_count = PlayerMetricRecord.objects.filter(player_training=player_training).count()
        print(f"📊 PlayerMetricRecord count after assignment: {after_assignment_count}")
        
        # Test 4: Check assigned metrics
        assigned_metrics = list(player_training.assigned_metrics.all())
        print(f"🎯 Assigned metrics: {[m.name for m in assigned_metrics]}")
        
        # Test 5: Verify serializer output
        from trainings.serializers import PlayerTrainingSerializer
        serializer = PlayerTrainingSerializer(player_training)
        metric_records_data = serializer.data['metric_records']
        print(f"📦 Serializer metric_records count: {len(metric_records_data)}")
        
        for record in metric_records_data:
            print(f"   📝 Metric: {record['metric_name']}, Value: {record['value']}, ID: {record['id']}")
        
        # Assertions
        assert result['success'] == True, f"Assignment should succeed, got: {result}"
        assert len(result['created_records']) == 0, f"No actual records should be created, got: {result['created_records']}"
        assert after_assignment_count == initial_record_count, f"No PlayerMetricRecord instances should be created. Before: {initial_record_count}, After: {after_assignment_count}"
        assert len(assigned_metrics) == 2, f"Two metrics should be assigned, got: {len(assigned_metrics)}"
        assert len(metric_records_data) == 2, f"Serializer should return 2 metric records, got: {len(metric_records_data)}"
        
        # Check that placeholder records have null values
        placeholder_count = 0
        for record in metric_records_data:
            if record['id'] is None:  # Placeholder record
                placeholder_count += 1
                assert record['value'] is None, f"Placeholder record should have null value, got {record['value']}"
                print(f"   ✅ Placeholder record for {record['metric_name']} has null value")
        
        assert placeholder_count == 2, f"Should have 2 placeholder records, got: {placeholder_count}"
        
        print("🎉 All tests passed! Metric assignment working correctly without creating placeholder records.")
        
        # Test 6: Now record an actual value and verify it shows up
        print("🔧 Testing actual metric recording...")
        
        # Create an actual metric record
        actual_record = PlayerMetricRecord.objects.create(
            player_training=player_training,
            metric=metric1,
            value=25.0,
            notes="Test recording"
        )
        
        # Check serializer output again
        serializer = PlayerTrainingSerializer(player_training)
        metric_records_data = serializer.data['metric_records']
        
        actual_record_found = False
        placeholder_found = False
        
        for record in metric_records_data:
            if record['id'] is not None and record['metric_name'] == metric1.name:
                actual_record_found = True
                assert record['value'] == 25.0, f"Actual record should have value 25.0, got: {record['value']}"
                print(f"   ✅ Actual record for {record['metric_name']} has correct value: {record['value']}")
            elif record['id'] is None and record['metric_name'] == metric2.name:
                placeholder_found = True
                assert record['value'] is None, f"Placeholder record should still have null value, got: {record['value']}"
                print(f"   ✅ Placeholder record for {record['metric_name']} still has null value")
        
        assert actual_record_found, "Should find the actual metric record"
        assert placeholder_found, "Should still find the placeholder record for unrecorded metric"
        
        print("🎉 Actual metric recording test passed!")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        raise e
    
    finally:
        # Cleanup
        print("🧹 Cleaning up test data...")
        try:
            # Clean up in reverse order of creation
            PlayerMetricRecord.objects.filter(player_training=player_training).delete()
            player_training.delete()
            session.delete()
            metric1.delete()
            metric2.delete()
            player.delete()
            coach.delete()
            team.delete()
            player_user.delete()
            coach_user.delete()
            print("✅ Cleanup completed")
        except Exception as cleanup_error:
            print(f"⚠️  Cleanup warning: {cleanup_error}")

if __name__ == "__main__":
    test_metric_assignment()
