#!/usr/bin/env python
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')
django.setup()

from trainings.models import PlayerTraining

pt = PlayerTraining.objects.get(id=2451)
print('✅ Final verification:')
print(f'Player: {pt.player}')
print(f'Session: {pt.session}')
print(f'Assigned metrics: {list(pt.assigned_metrics.values_list("name", flat=True))}')
print(f'Metric records count: {pt.metric_records.count()}')
print('Metric records details:')
for record in pt.metric_records.all():
    print(f'  - {record.metric.name}: {record.value} ({record.notes})')
