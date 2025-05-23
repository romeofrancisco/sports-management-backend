from django.db import migrations, models


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
    
    for unit_data in default_units:
        MetricUnit.objects.get_or_create(
            code=unit_data['code'],
            defaults={
                'name': unit_data['name'],
                'normalization_weight': unit_data['weight']
            }
        )


def migrate_to_metric_units(apps, schema_editor):
    TrainingMetric = apps.get_model('trainings', 'TrainingMetric')
    MetricUnit = apps.get_model('trainings', 'MetricUnit')
    
    # Process all metrics that still have a unit field
    for metric in TrainingMetric.objects.filter(metric_unit__isnull=True):
        if metric.unit:  # Only process if there's a unit value
            try:
                # Try to find existing unit
                unit = MetricUnit.objects.get(code=metric.unit)
            except MetricUnit.DoesNotExist:
                # Create new unit if it doesn't exist
                unit = MetricUnit.objects.create(
                    code=metric.unit,
                    name=metric.unit.title(),
                    normalization_weight=1.0  # Default weight
                )
            metric.metric_unit = unit
            metric.save()


def reverse_metric_units_migration(apps, schema_editor):
    TrainingMetric = apps.get_model('trainings', 'TrainingMetric')
    # Copy metric_unit.code back to unit field
    for metric in TrainingMetric.objects.all():
        if metric.metric_unit:
            metric.unit = metric.metric_unit.code
            metric.save()


class Migration(migrations.Migration):

    dependencies = [
        ('trainings', '0012_populate_metric_units'),
    ]

    operations = [
        # Create MetricUnit model
        migrations.CreateModel(
            name='MetricUnit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=50, unique=True)),
                ('name', models.CharField(max_length=100)),
                ('normalization_weight', models.DecimalField(decimal_places=2, default=1.0, max_digits=5)),
            ],
        ),
        # Add metric_unit field to TrainingMetric
        migrations.AddField(
            model_name='trainingmetric',
            name='metric_unit',
            field=models.ForeignKey(null=True, on_delete=models.deletion.SET_NULL, to='trainings.metricunit'),
        ),
        # Populate metric units
        migrations.RunPython(populate_metric_units),
        # Migrate existing metrics to use metric_unit
        migrations.RunPython(migrate_to_metric_units, reverse_metric_units_migration),
        # Remove old unit field
        migrations.RemoveField(
            model_name='trainingmetric',
            name='unit',
        ),
    ]
