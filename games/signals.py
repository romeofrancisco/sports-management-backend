from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import PlayerStat
from games.models import Game
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def send_score_update(game):
    """Send real-time score update via WebSocket"""
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            f'game_score_{game.id}',
            {
                'type': 'score_update',
                'game_id': game.id,
                'home_team_score': game.home_team_score,
                'away_team_score': game.away_team_score,
                'home_team_id': game.home_team.id,
                'away_team_id': game.away_team.id,
                'home_team_name': game.home_team.name,
                'away_team_name': game.away_team.name,
                'status': game.status,
                'current_period': game.current_period,
                'timestamp': datetime.now().isoformat()
            }
        )

def send_game_status_update(game):
    """Send real-time game status update via WebSocket"""
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            f'game_score_{game.id}',
            {
                'type': 'game_status_update',
                'game_id': game.id,
                'status': game.status,
                'current_period': game.current_period,
                'started_at': game.started_at.isoformat() if game.started_at else None,
                'ended_at': game.ended_at.isoformat() if game.ended_at else None,
                'timestamp': datetime.now().isoformat()
            }
        )
    
@receiver([post_save, post_delete], sender=PlayerStat)
def update_game_score(sender, instance, **kwargs):
    try:
        if hasattr(instance, 'game') and instance.game and instance.game.status == Game.Status.IN_PROGRESS:
            # Store the old scores for comparison
            old_home_score = instance.game.home_team_score
            old_away_score = instance.game.away_team_score
            
            # Update the scores
            instance.game.update_scores()
            
            # Send WebSocket update if scores actually changed
            if (instance.game.home_team_score != old_home_score or 
                instance.game.away_team_score != old_away_score):
                send_score_update(instance.game)
                
    except Game.DoesNotExist:
        # Game might have been deleted already
        logger.info(f"Game for PlayerStat {instance.id} no longer exists, skipping score update")
    except Exception as e:
        logger.error(f"Error updating game score: {str(e)}")

@receiver(post_save, sender=Game)
def handle_game_status_change(sender, instance, created, **kwargs):
    """Send WebSocket update when game status changes"""
    if not created and instance.status in [Game.Status.IN_PROGRESS, Game.Status.COMPLETED]:
        try:
            send_game_status_update(instance)
        except Exception as e:
            logger.error(f"Error sending game status update: {str(e)}")
    
    # Also send score updates when the game is saved with score changes
    if not created and instance.status == Game.Status.IN_PROGRESS:
        try:
            send_score_update(instance)
        except Exception as e:
            logger.error(f"Error sending score update on game save: {str(e)}")