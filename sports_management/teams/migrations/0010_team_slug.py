# Generated by Django 5.1.6 on 2025-03-19 09:27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0009_alter_team_logo'),
    ]

    operations = [
        migrations.AddField(
            model_name='team',
            name='slug',
            field=models.SlugField(blank=True, unique=True),
        ),
    ]
