# Generated manually
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('trainings', '0012_populate_metric_units'),
    ]
    
    operations = [
        # Make metric_unit required
        migrations.AlterField(
            model_name='trainingmetric',
            name='metric_unit',
            field=models.ForeignKey(
                help_text='The unit of measurement for this metric',
                on_delete=models.PROTECT,
                related_name='metrics',
                to='trainings.metricunit'
            ),
        ),
        # Update TrainingMetric.__str__ to use metric_unit.code
        migrations.AlterModelOptions(
            name='trainingmetric',
            options={},
        ),
    ]
