# Generated by Django 5.1.6 on 2025-04-01 11:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0005_league_elimination_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='season',
            name='record_stats',
            field=models.BooleanField(default=True),
        ),
    ]
