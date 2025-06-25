from django.db.models.signals import post_save
from django.dispatch import receiver
from teams.models import Team
from .models import TeamChat

@receiver(post_save, sender=Team)
def create_team_chat(sender, instance, created, **kwargs):
    """
    Automatically create a TeamChat instance when a new Team is created
    """
    if created:
        TeamChat.objects.create(team=instance)
