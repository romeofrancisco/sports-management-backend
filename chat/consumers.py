import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from .models import TeamChat, ChatMessage
from teams.models import Team, Coach, Player
from users.models import User

class TeamChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.team_id = self.scope['url_route']['kwargs']['team_id']
        self.room_group_name = f'chat_team_{self.team_id}'
        
        # Check if user is authenticated and can access this team chat
        user = self.scope["user"]
        if isinstance(user, AnonymousUser):
            await self.close()
            return
            
        can_access = await self.user_can_access_team_chat(user, self.team_id)
        if not can_access:
            await self.close()
            return
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            text_data_json = json.loads(text_data)
            message = text_data_json['message']
            user = self.scope["user"]
              # Save message to database
            chat_message = await self.save_message(user, self.team_id, message)
            
            if chat_message:
                # Get user profile info
                profile_info = await self.get_user_profile(user)
                  # Send message to room group
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message',
                        'team_id': self.team_id,
                        'message': message,
                        'sender_name': user.get_full_name(),
                        'sender_id': user.id,
                        'sender_role': user.role,
                        'profile': profile_info,
                        'timestamp': chat_message.timestamp.isoformat(),
                        'message_id': chat_message.id
                    })
        except Exception as e:
            await self.send(text_data=json.dumps({
                'error': f'Error processing message: {str(e)}'            }))

    async def chat_message(self, event):
        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'team_id': event.get('team_id'),
            'message': event['message'],
            'sender_name': event['sender_name'],
            'sender_id': event['sender_id'],
            'sender_role': event['sender_role'],
            'profile': event.get('profile', {}),
            'timestamp': event['timestamp'],
            'message_id': event['message_id']
        }))

    @database_sync_to_async
    def get_user_profile(self, user):
        """
        Get user profile information
        """
        try:
            profile_data = {
                'profile_picture': None,
                'position': None,
                'jersey_number': None,
            }
            
            if user.role == 'Player':
                try:
                    player = Player.objects.get(user=user)
                    profile_data['profile_picture'] = player.profile_picture.url if player.profile_picture else None
                    profile_data['position'] = player.position
                    profile_data['jersey_number'] = player.jersey_number
                except Player.DoesNotExist:
                    pass
            elif user.role == 'Coach':
                try:
                    coach = Coach.objects.get(user=user)
                    profile_data['profile_picture'] = coach.profile_picture.url if coach.profile_picture else None
                except Coach.DoesNotExist:
                    pass
                    
            return profile_data
        except Exception as e:
            print(f"Error getting user profile: {e}")
            return {}

    @database_sync_to_async
    def user_can_access_team_chat(self, user, team_id):
        """
        Check if user can access this team chat based on their role
        """
        try:
            team = Team.objects.get(id=team_id)
            
            # Admin can access all team chats
            if user.is_admin:
                return True
                
            # Coach can access if they coach this team
            if user.role == 'Coach':
                try:
                    coach = Coach.objects.get(user=user)
                    return team in coach.teams.all()
                except Coach.DoesNotExist:
                    return False
                    
            # Player can access if they're on this team
            if user.role == 'Player':
                try:
                    player = Player.objects.get(user=user)
                    return team == player.team
                except Player.DoesNotExist:
                    return False
                    
            return False
        except Team.DoesNotExist:
            return False

    @database_sync_to_async
    def save_message(self, user, team_id, message):
        """
        Save chat message to database
        """
        try:
            team = Team.objects.get(id=team_id)
            team_chat, created = TeamChat.objects.get_or_create(team=team)
            
            chat_message = ChatMessage.objects.create(
                team_chat=team_chat,
                sender=user,
                message=message
            )
            return chat_message
        except Exception as e:
            print(f"Error saving message: {e}")
            return None

class GlobalChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Check if user is authenticated
        user = self.scope["user"]
        if isinstance(user, AnonymousUser):
            await self.close()
            return
        
        self.user = user
        self.user_id = user.id
        
        # Get all teams this user has access to
        team_ids = await self.get_user_team_ids(user)
        
        # Join all team chat groups this user has access to
        self.team_groups = []
        for team_id in team_ids:
            group_name = f'chat_team_{team_id}'
            self.team_groups.append(group_name)
            await self.channel_layer.group_add(
                group_name,
                self.channel_name
            )        
        print(f"Global chat connected for user {user.id} to teams: {team_ids}")
        await self.accept()

    async def disconnect(self, close_code):
        # Leave all room groups
        for group_name in getattr(self, 'team_groups', []):
            await self.channel_layer.group_discard(
                group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        # Global consumers don't handle message sending, only receiving
        # Messages are sent via team-specific consumers
        pass

    async def chat_message(self, event):
        # Forward the message to the WebSocket client with team_id
        team_id = event.get('team_id')
        if not team_id:
            # Extract team_id from the group name if not provided
            # Group name format: 'chat_team_{team_id}'
            for group in getattr(self, 'team_groups', []):
                if f'chat_team_' in group:
                    team_id = group.split('chat_team_')[1]
                    break
        
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'team_id': team_id,
            'message': event['message'],
            'sender_name': event['sender_name'],
            'sender_id': event['sender_id'],
            'sender_role': event['sender_role'],
            'profile': event.get('profile', {}),
            'timestamp': event['timestamp'],
            'message_id': event['message_id']
        }))

    @database_sync_to_async
    def get_user_team_ids(self, user):
        """
        Get all team IDs this user has access to
        """
        try:
            team_ids = []
            
            # Admin can access all team chats
            if user.is_admin:
                team_ids = list(Team.objects.values_list('id', flat=True))
            elif user.role == 'Coach':
                try:
                    coach = Coach.objects.get(user=user)
                    team_ids = list(coach.teams.values_list('id', flat=True))
                except Coach.DoesNotExist:
                    pass
            elif user.role == 'Player':
                try:
                    player = Player.objects.get(user=user)
                    if player.team:
                        team_ids = [player.team.id]
                except Player.DoesNotExist:
                    pass
                    
            return team_ids
        except Exception as e:
            print(f"Error getting user team IDs: {e}")
            return []
