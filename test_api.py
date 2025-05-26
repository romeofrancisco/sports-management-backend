#!/usr/bin/env python
import os
import sys
import django

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')
django.setup()

from trainings.models import PlayerTraining, TrainingMetric, PlayerMetricRecord
from trainings.services.player_training_service import PlayerTrainingService

def test_assign_metrics():
    print("=== Testing PlayerTraining and TrainingMetric data ===")
    print(f"PlayerTraining count: {PlayerTraining.objects.count()}")
    print(f"TrainingMetric count: {TrainingMetric.objects.count()}")
    print(f"PlayerMetricRecord count: {PlayerMetricRecord.objects.count()}")
    
    if not PlayerTraining.objects.exists():
        print("No PlayerTraining records found. Cannot test.")
        return
        
    if not TrainingMetric.objects.exists():
        print("No TrainingMetric records found. Cannot test.")
        return
    
    # Get first player training record
    pt = PlayerTraining.objects.first()
    print(f"\nTesting with PlayerTraining ID: {pt.id}")
    print(f"Player: {pt.player}")
    print(f"Session: {pt.session}")
    
    # Get some metrics to test with
    metrics = list(TrainingMetric.objects.all()[:3])  # Get first 3 metrics
    metric_ids = [m.id for m in metrics]
    
    print(f"\nBefore assignment:")
    print(f"Assigned metrics: {list(pt.assigned_metrics.values_list('id', flat=True))}")
    print(f"Metric records: {list(pt.metric_records.values_list('id', 'metric__name', 'value'))}")
    
    # Test the service method
    print(f"\nAssigning metrics: {metric_ids}")
    result = PlayerTrainingService.assign_metrics_to_player_training(pt, metric_ids)
    print(f"Service result: {result}")
    
    # Check after assignment
    pt.refresh_from_db()
    print(f"\nAfter assignment:")
    print(f"Assigned metrics: {list(pt.assigned_metrics.values_list('id', flat=True))}")
    print(f"Metric records: {list(pt.metric_records.values_list('id', 'metric__name', 'value'))}")
    
    # Check the specific records created
    created_records = PlayerMetricRecord.objects.filter(
        player_training=pt,
        metric__in=metrics
    ).values('id', 'metric__name', 'value', 'notes')
    
    print(f"\nCreated PlayerMetricRecord instances:")
    for record in created_records:
        print(f"  - {record}")

if __name__ == "__main__":
    test_assign_metrics()
