# Generated by Django 5.1.6 on 2025-04-01 12:40

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('games', '0015_alter_game_league'),
        ('leagues', '0007_season_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='game',
            name='league',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='games', to='leagues.league'),
        ),
        migrations.AlterField(
            model_name='game',
            name='season',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='leagues.season'),
        ),
    ]
