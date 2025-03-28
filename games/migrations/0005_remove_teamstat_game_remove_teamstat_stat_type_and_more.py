# Generated by Django 5.1.6 on 2025-03-18 06:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('games', '0004_playerstat_percentage'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='teamstat',
            name='game',
        ),
        migrations.RemoveField(
            model_name='teamstat',
            name='stat_type',
        ),
        migrations.RemoveField(
            model_name='teamstat',
            name='team',
        ),
        migrations.AddField(
            model_name='game',
            name='away_team_score',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='game',
            name='current_period',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='game',
            name='home_team_score',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.DeleteModel(
            name='PlayerStat',
        ),
        migrations.DeleteModel(
            name='TeamStat',
        ),
    ]
