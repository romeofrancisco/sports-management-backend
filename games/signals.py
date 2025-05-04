from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import PlayerStat
from games.models import Game
import logging

logger = logging.getLogger(__name__)
    
@receiver([post_save, post_delete], sender=PlayerStat)
def update_game_score(sender, instance, **kwargs):
    try:
        if hasattr(instance, 'game') and instance.game and instance.game.status == Game.Status.IN_PROGRESS:
            instance.game.update_scores()
    except Game.DoesNotExist:
        # Game might have been deleted already
        logger.info(f"Game for PlayerStat {instance.id} no longer exists, skipping score update")
    except Exception as e:
        logger.error(f"Error updating game score: {str(e)}")