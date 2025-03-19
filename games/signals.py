from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import PlayerStat

@receiver([post_save, post_delete], sender=PlayerStat)
def update_game_score(sender, instance, **kwargs):
    instance.game.update_scores()