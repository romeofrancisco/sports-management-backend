#!/usr/bin/env python
import os
import sys
import django

# Add the project directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')
django.setup()

from django.urls import reverse
from rest_framework.routers import DefaultRouter
from trainings.views import PlayerTrainingViewSet

# Create router and register the viewset
router = DefaultRouter()
router.register(r'player-trainings', PlayerTrainingViewSet)

# Print all URLs
print("Generated URLs for PlayerTrainingViewSet:")
for pattern in router.urls:
    print(f"  {pattern.pattern}")

# Try to reverse the assign_metrics action
try:
    url = reverse('playertraining-assign-metrics', kwargs={'pk': 1})
    print(f"\nReversed URL for assign-metrics action: {url}")
except Exception as e:
    print(f"\nError reversing assign-metrics URL: {e}")
