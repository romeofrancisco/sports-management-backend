#!/usr/bin/env python
"""
Test script to verify that metric assignment doesn't create placeholder records with value 0
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')
django.setup()

from django.test import TestCase
from trainings.models import TrainingSession, PlayerTraining, TrainingMetric, PlayerMetricRecord, TrainingCategory, MetricUnit
from trainings.services.player_training_service import PlayerTrainingService
from teams.models import Player, Team, Coach
from users.models import User
from django.utils import timezone
from datetime import datetime

def test_metric_assignment():
    """Test that newly assigned metrics don't create placeholder records with value 0"""
    
    print("🧪 Testing metric assignment behavior...")
    
    # Create test data
    print("📝 Creating test data...")    # Create a user for the coach
    coach_user = User.objects.create_user(
        email="coach@test.com",
        first_name="Test",
        last_name="Coach",
        password="testpass123"
    )
    
    # Create a team
    team = Team.objects.create(
        name="Test Team",
        acronym="TT",
        home_court="Test Court"
    )
    
    # Create a coach
    coach = Coach.objects.create(
        user=coach_user,
        contact_number="1234567890"
    )
    coach.teams.add(team)    # Create a user for the player
    player_user = User.objects.create_user(
        email="player@test.com",
        first_name="Test",
        last_name="Player",
        password="testpass123"
    )
    
    # Create a player
    player = Player.objects.create(
        user=player_user,
        jersey_number=10,
        position="PG",
        team=team
    )
    
    # Create training session
    session = TrainingSession.objects.create(
        title="Test Session",
        date=timezone.now().date(),
        start_time=timezone.now().time(),
        end_time=timezone.now().time(),
        team=team,
        coach=coach
    )
    
    # Create player training record
    player_training = PlayerTraining.objects.create(
        player=player,
        session=session,
        attendance_status='present'
    )
    
    # Create metric unit and category
    metric_unit = MetricUnit.objects.create(
        name="Repetitions",
        code="reps",
        description="Number of repetitions"
    )
    
    category = TrainingCategory.objects.create(
        name="Strength",
        description="Strength training metrics"
    )
    
    # Create training metrics
    metric1 = TrainingMetric.objects.create(
        name="Push-ups",
        description="Number of push-ups completed",
        metric_unit=metric_unit,
        category=category,
        is_lower_better=False
    )
    
    metric2 = TrainingMetric.objects.create(
        name="Sit-ups",
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
    assert result['success'] == True, "Assignment should succeed"
    assert len(result['created_records']) == 0, "No actual records should be created"
    assert after_assignment_count == initial_record_count, "No PlayerMetricRecord instances should be created"
    assert len(assigned_metrics) == 2, "Two metrics should be assigned"
    assert len(metric_records_data) == 2, "Serializer should return 2 metric records"
    
    # Check that placeholder records have null values
    for record in metric_records_data:
        if record['id'] is None:  # Placeholder record
            assert record['value'] is None, f"Placeholder record should have null value, got {record['value']}"
            print(f"   ✅ Placeholder record for {record['metric_name']} has null value")
    
    print("🎉 All tests passed! Metric assignment working correctly without creating placeholder records.")
    
    # Cleanup
    print("🧹 Cleaning up test data...")
    PlayerMetricRecord.objects.filter(player_training=player_training).delete()
    player_training.delete()
    session.delete()
    metric1.delete()
    metric2.delete()
    category.delete()
    metric_unit.delete()
    player.delete()
    coach.delete()
    team.delete()
    player_user.delete()
    coach_user.delete()
    
    print("✅ Cleanup completed")

if __name__ == "__main__":
    test_metric_assignment()
