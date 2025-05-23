from django.db import migrations


def populate_metric_units(apps, schema_editor):
    MetricUnit = apps.get_model('trainings', 'MetricUnit')
    
    # Define default units with their weights
    default_units = [
        {'code': 'seconds', 'name': 'Seconds', 'weight': 1.0},
        {'code': 'minutes', 'name': 'Minutes', 'weight': 1.0},
        {'code': 'meters', 'name': 'Meters', 'weight': 0.5},
        {'code': 'm', 'name': 'Meters', 'weight': 0.5},
        {'code': 'km', 'name': 'Kilometers', 'weight': 0.5},
        {'code': 'reps', 'name': 'Repetitions', 'weight': 0.2},
        {'code': 'kg', 'name': 'Kilograms', 'weight': 0.5},
        {'code': 'lbs', 'name': 'Pounds', 'weight': 0.5},
        {'code': 'bpm', 'name': 'Beats Per Minute', 'weight': 0.7},
        {'code': 'in', 'name': 'Inches', 'weight': 0.5},
        {'code': '%', 'name': 'Percentage', 'weight': 1.0},
    ]
    
    # Create units if they don't exist
    for unit_data in default_units:
        MetricUnit.objects.get_or_create(
            code=unit_data['code'],
            defaults={
                'name': unit_data['name'],
                'normalization_weight': unit_data['weight']
            }
        )


def migrate_metrics_to_units(apps, schema_editor):
    TrainingMetric = apps.get_model('trainings', 'TrainingMetric')
    MetricUnit = apps.get_model('trainings', 'MetricUnit')
    
    # Process all metrics that still have a unit field
    for metric in TrainingMetric.objects.filter(metric_unit__isnull=True):
        if metric.unit:  # Only process if there's a unit value
            unit, created = MetricUnit.objects.get_or_create(
                code=metric.unit,
                defaults={
                    'name': metric.unit.title(),
                    'normalization_weight': 1.0  # Default weight
                }
            )
            metric.metric_unit = unit
            metric.save()


class Migration(migrations.Migration):    
    dependencies = [
        ('trainings', '0013_metric_units_complete'),
    ]

    operations = [
        migrations.RunPython(populate_metric_units),
        migrations.RunPython(migrate_metrics_to_units),
    ]
