#!/usr/bin/env python
import os
import sys
import django

# Setup Django
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')
django.setup()

from trainings.models import TrainingSession
from trainings.services.training_completion_service import TrainingCompletionService

def test_completion_rate():
    """Test the completion rate calculation with the new logic"""
    
    # Get a completed session to test
    session = TrainingSession.objects.filter(status='completed').first()
    
    if not session:
        print("No completed sessions found")
        return
    
    print(f"Testing session: {session.title} on {session.date}")
    print("-" * 50)
    
    # Get the metrics summary using the updated calculation
    metrics_summary = TrainingCompletionService._calculate_metrics_summary(session)
    
    print(f"Total metrics recorded: {metrics_summary['total_metrics_recorded']}")
    print(f"Unique metrics: {metrics_summary['unique_metrics']}")
    print(f"Players with metrics: {metrics_summary['players_with_metrics']}")
    print(f"Expected records: {metrics_summary['expected_records']}")
    print(f"Completion rate: {metrics_summary['completion_rate']}%")
    
    # Show breakdown
    print("\nMetrics breakdown:")
    for metric_data in metrics_summary['metrics_breakdown']:
        print(f"  {metric_data['metric__name']}: {metric_data['records_count']} records, {metric_data['unique_players']} players")

if __name__ == "__main__":
    test_completion_rate()
