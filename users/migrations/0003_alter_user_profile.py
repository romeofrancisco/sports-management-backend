# Generated by Django 5.1.6 on 2025-03-19 12:45

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_alter_user_profile'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='profile',
            field=models.ImageField(null=True, upload_to='users/'),
        ),
    ]
