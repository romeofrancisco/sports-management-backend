# Generated by Django 5.1.6 on 2025-03-16 09:45

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('games', '0002_teamstat_attempted_teamstat_made_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='teamstat',
            name='percentage',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
    ]
