# Generated manually

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('trainings', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='trainingcategory',
            name='slug',
        ),
    ]
