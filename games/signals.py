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
    import time
    start_time = time.time()
    
    channel_layer = get_channel_layer()
    if channel_layer:
        try:
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
                    'sport_scoring_type': game.sport.scoring_type,
                    'timestamp': datetime.now().isoformat(),
                    'update_type': 'incremental'  # Mark as incremental update
                }
            )
            logger.debug(f"Score update sent in {time.time() - start_time:.4f}s")
        except Exception as e:
            print(f"ERROR sending WebSocket update: {str(e)}")
            logger.error(f"Failed to send score update: {str(e)}")
    else:
        print("ERROR: No channel layer available!")

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
    import time
    start_time = time.time()
    
    print(f"SIGNAL TRIGGERED: PlayerStat {instance.id} {'saved' if kwargs.get('signal') == post_save else 'deleted'} for game {instance.game_id}")
    
    try:
        if hasattr(instance, 'game') and instance.game and instance.game.status == Game.Status.IN_PROGRESS:
            # Determine if this is a creation, update, or deletion
            is_deletion = kwargs.get('signal') == post_delete
            is_creation = kwargs.get('created', False)
            
            print(f"Processing stat change: deletion={is_deletion}, creation={is_creation}")
            
            if is_deletion:
                # Stat deleted - remove points
                instance.game.update_scores_incremental(instance, 'remove')
            elif is_creation:
                # Stat created - add points
                instance.game.update_scores_incremental(instance, 'add')
            else:
                # Stat updated - fall back to full recalculation
                instance.game.update_scores()
            
            # Send WebSocket update
            print(f"Sending WebSocket update for game {instance.game.id}")
            send_score_update(instance.game)
            logger.debug(f"Game score update completed in {time.time() - start_time:.4f}s")
                
    except Game.DoesNotExist:
        # Game might have been deleted already
        logger.info(f"Game for PlayerStat {instance.id} no longer exists, skipping score update")
    except Exception as e:
        logger.error(f"Error updating game score: {str(e)}")
        # Fallback to full recalculation on error
        try:
            if hasattr(instance, 'game') and instance.game:
                instance.game.update_scores()
                send_score_update(instance.game)
        except Exception as fallback_error:
            logger.error(f"Fallback score update also failed: {str(fallback_error)}")

@receiver(post_save, sender=Game)
def handle_game_status_change(sender, instance, created, **kwargs):
    """Send WebSocket update when game status changes"""
    if not created and instance.status in [Game.Status.IN_PROGRESS, Game.Status.COMPLETED]:
        try:
            send_game_status_update(instance)
        except Exception as e:
            logger.error(f"Error sending game status update: {str(e)}")
    
    # Only send score updates for manual score changes (not triggered by PlayerStat signals)
    # Check if this save was triggered by a score update that's not from PlayerStat
    if not created and instance.status == Game.Status.IN_PROGRESS:
        # We'll let the PlayerStat signal handle score updates to avoid duplicates
        # Only send score updates for manual operations or other score changes
        pass