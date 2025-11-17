import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from .models import Game


class GameScoreConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.game_id = self.scope['url_route']['kwargs']['game_id']
        self.room_group_name = f'game_score_{self.game_id}'
        
        # Check if user is authenticated and can access this game
        user = self.scope["user"]
        
        if isinstance(user, AnonymousUser):
            await self.close()
            return
            
        can_access = await self.user_can_access_game(user, self.game_id)
        
        if not can_access:
            await self.close()
            return        
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        print(f"WebSocket connected for game {self.game_id}, user {user}")

    async def disconnect(self, close_code):
        """Leave room group"""
        print(f"Disconnecting WebSocket for game {self.game_id} with code {close_code}")
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        # For now, this consumer is primarily for receiving updates, not sending them
        # Score updates should be triggered by the backend API views
        pass

    async def score_update(self, event):
        """Send score update to WebSocket"""
        print(f"Sending score update for game {self.game_id}: {event}")
        await self.send(text_data=json.dumps({
            'type': 'score_update',
            'game_id': event['game_id'],
            'home_team_score': event['home_team_score'],
            'away_team_score': event['away_team_score'],
            'home_team_id': event['home_team_id'],
            'away_team_id': event['away_team_id'],
            'home_team_name': event['home_team_name'],
            'away_team_name': event['away_team_name'],
            'status': event.get('status'),
            'current_period': event.get('current_period'),
            'sport_scoring_type': event.get('sport_scoring_type'),
            'timestamp': event['timestamp']
        }))

    async def game_status_update(self, event):
        """Send game status update to WebSocket"""
        print(f"Sending game status update for game {self.game_id}: {event}")
        await self.send(text_data=json.dumps({
            'type': 'game_status_update',
            'game_id': event['game_id'],
            'status': event['status'],
            'current_period': event.get('current_period'),
            'started_at': event.get('started_at'),
            'ended_at': event.get('ended_at'),            
            'timestamp': event['timestamp']
        }))    
    
    @database_sync_to_async
    def user_can_access_game(self, user, game_id):
        """
        Check if user can access this game's real-time updates
        For now, allow all authenticated users (can be restricted later)
        """
        try:
            # Simple check - just verify game exists and allow all authenticated users
            game = Game.objects.get(id=game_id)
            return True
            
        except Game.DoesNotExist:
            return False
        except Exception as e:
            return False
