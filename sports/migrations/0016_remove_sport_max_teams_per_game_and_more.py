# Generated by Django 5.1.6 on 2025-03-28 11:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sports', '0015_sport_max_players_per_team_sport_max_teams_per_game'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='sport',
            name='max_teams_per_game',
        ),
        migrations.AddField(
            model_name='sport',
            name='max_players_on_field',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
