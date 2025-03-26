from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import PlayerStat
from games.models import Game
    
@receiver([post_save, post_delete], sender=PlayerStat)
def update_game_score(sender, instance, **kwargs):
    if instance.game.status == Game.Status.IN_PROGRESS:
        instance.game.update_scores()