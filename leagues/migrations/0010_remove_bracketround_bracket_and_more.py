# Generated by Django 5.1.6 on 2025-04-09 06:38

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0009_alter_bracketmatch_options_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='bracketround',
            name='bracket',
        ),
        migrations.RemoveField(
            model_name='bracketmatch',
            name='bracket',
        ),
        migrations.RemoveField(
            model_name='bracketmatch',
            name='away_team',
        ),
        migrations.RemoveField(
            model_name='bracketmatch',
            name='game',
        ),
        migrations.RemoveField(
            model_name='bracketmatch',
            name='home_team',
        ),
        migrations.RemoveField(
            model_name='bracketmatch',
            name='round',
        ),
        migrations.DeleteModel(
            name='Bracket',
        ),
        migrations.DeleteModel(
            name='BracketMatch',
        ),
        migrations.DeleteModel(
            name='BracketRound',
        ),
    ]
