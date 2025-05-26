#!/usr/bin/env python
"""
Test script to simulate the exact frontend flow for SessionMetricsConfigModal
"""
import os
import sys
import django

# Add the project directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')
django.setup()

import json
from django.test import Client
from django.contrib.auth import get_user_model
from trainings.models import TrainingSession, PlayerTraining, TrainingMetric, PlayerMetricRecord

def test_frontend_flow():
    """Test the exact flow from SessionMetricsConfigModal"""
    print("=== Testing Frontend SessionMetricsConfigModal Flow ===\n")
    
    try:
        # Create a client to make API requests
        client = Client()
        
        # Get an admin user or create one
        User = get_user_model()
        admin_user, _ = User.objects.get_or_create(
            email='admin@test.com',
            defaults={
                'first_name': 'Admin',
                'last_name': 'User',
                'role': 'Admin',
                'is_staff': True,
                'is_superuser': True
            }
        )
        
        # Login the user
        client.force_login(admin_user)
          # Get a session that has player trainings
        session_with_players = TrainingSession.objects.filter(
            player_records__isnull=False
        ).first()
        
        if not session_with_players:
            print("❌ No training session with players found. Please create some test data first.")
            return False
            
        print(f"1. Using session: {session_with_players.title}")
        
        # Get some available metrics
        available_metrics = list(TrainingMetric.objects.all()[:4])
        
        if len(available_metrics) < 3:
            print("❌ Need at least 3 metrics available. Please create some test metrics first.")
            return False
            
        print(f"2. Available metrics: {[m.name for m in available_metrics]}")
        
        # Step 1: Assign initial metrics (simulate selecting metrics in modal)
        initial_metric_ids = [m.id for m in available_metrics[:3]]
        print(f"\n3. Assigning initial metrics: {[available_metrics[i].name for i in range(3)]}")
        
        response = client.post(
            f'/api/trainings/sessions/{session_with_players.id}/assign_metrics/',
            data=json.dumps({'metrics': initial_metric_ids}),
            content_type='application/json'
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✓ API Response: {result['detail']}")
            print(f"✓ Created {result.get('created_records', 0)} records")
            
            # Verify records were created
            record_count = PlayerMetricRecord.objects.filter(
                player_training__session=session_with_players,
                metric__in=initial_metric_ids
            ).count()
            print(f"✓ Database shows {record_count} metric records")
        else:
            print(f"❌ API call failed: {response.status_code} - {response.content}")
            return False
        
        # Step 2: Simulate unchecking one metric in the modal
        reduced_metric_ids = initial_metric_ids[:2]  # Remove the last metric
        removed_metric = available_metrics[2]
        print(f"\n4. Unchecking metric: {removed_metric.name}")
        print(f"   Keeping metrics: {[available_metrics[i].name for i in range(2)]}")
        
        response = client.post(
            f'/api/trainings/sessions/{session_with_players.id}/assign_metrics/',
            data=json.dumps({'metrics': reduced_metric_ids}),
            content_type='application/json'
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✓ API Response: {result['detail']}")
            print(f"✓ Deleted {result.get('updated_records', 0)} old records")
            
            # Verify the unchecked metric was removed from all players
            removed_metric_records = PlayerMetricRecord.objects.filter(
                player_training__session=session_with_players,
                metric=removed_metric
            ).count()
            
            if removed_metric_records == 0:
                print(f"✓ Confirmed: {removed_metric.name} metric removed from all players in session")
            else:
                print(f"❌ Error: {removed_metric.name} metric still has {removed_metric_records} records")
                return False
                
            # Verify remaining metrics are still there
            remaining_record_count = PlayerMetricRecord.objects.filter(
                player_training__session=session_with_players,
                metric__in=reduced_metric_ids
            ).count()
            print(f"✓ Remaining metrics have {remaining_record_count} records")
            
        else:
            print(f"❌ API call failed: {response.status_code} - {response.content}")
            return False
        
        # Step 3: Simulate unchecking all metrics
        print(f"\n5. Unchecking all metrics (clearing session metrics)")
        
        response = client.post(
            f'/api/trainings/sessions/{session_with_players.id}/assign_metrics/',
            data=json.dumps({'metrics': []}),
            content_type='application/json'
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✓ API Response: {result['detail']}")
            print(f"✓ Deleted {result.get('updated_records', 0)} old records")
            
            # Verify all metrics were removed
            all_metric_records = PlayerMetricRecord.objects.filter(
                player_training__session=session_with_players
            ).count()
            
            if all_metric_records == 0:
                print("✓ Confirmed: All metrics removed from all players in session")
            else:
                print(f"❌ Error: {all_metric_records} metric records still exist")
                return False
                
        else:
            print(f"❌ API call failed: {response.status_code} - {response.content}")
            return False
        
        print("\n=== FRONTEND FLOW TEST PASSED! ===")
        print("✅ SessionMetricsConfigModal unchecking flow works correctly")
        print("✅ Metrics are properly removed from all players when unchecked")
        print("✅ API endpoints handle metric cleanup correctly")
        print("✅ Database stays consistent")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_frontend_flow()
    if success:
        print("\n🎉 The complete frontend-to-backend flow is working correctly!")
        print("🔧 The SessionMetricsConfigModal issue has been fully resolved!")
    else:
        print("\n❌ There are still issues in the frontend flow.")
