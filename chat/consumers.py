import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.db.models import Q
from push_notifications.models import WebPushDevice
from .models import TeamChat, ChatMessage
from teams.models import Team, Coach, Player

# -------------------------
# TEAM CHAT CONSUMER
# -------------------------
class TeamChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.team_id = self.scope['url_route']['kwargs']['team_id']
        self.room_group_name = f'chat_team_{self.team_id}'
        self.profile_cache = {}  # cache per connection

        user = self.scope["user"]
        if isinstance(user, AnonymousUser):
            await self.close()
            return

        if not await self.user_can_access_team_chat(user, self.team_id):
            await self.close()
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        try:
            await asyncio.wait_for(
                self.channel_layer.group_discard(self.room_group_name, self.channel_name),
                timeout=2
            )
        except asyncio.TimeoutError:
            print(f"Timeout discarding group {self.room_group_name}")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message = data['message']
            user = self.scope["user"]
            asyncio.create_task(self.save_and_broadcast(user, self.team_id, message))
        except Exception as e:
            await self.send(json.dumps({'error': f'Error processing message: {str(e)}'}))

    async def save_and_broadcast(self, user, team_id, message):
        chat_message = await self.save_message(user, team_id, message)
        if not chat_message:
            return

        # Get team for team name
        team = await database_sync_to_async(Team.objects.get)(id=team_id)

        # Check cache first
        if user.id in self.profile_cache:
            profile_info = self.profile_cache[user.id]
        else:
            profile_info = await self.get_user_profile(user)
            self.profile_cache[user.id] = profile_info

        await self.channel_layer.group_send(
            f'chat_team_{team_id}',
            {
                'type': 'chat_message',
                'team_id': team_id,
                'team_name': team.name,
                'message': message,
                'sender_name': user.get_full_name(),
                'sender_id': user.id,
                'sender_role': user.role,
                'profile': profile_info,
                'timestamp': chat_message.timestamp.isoformat(),
                'message_id': chat_message.id
            }
        )

        # Send push notifications to team members (excluding sender)
        asyncio.create_task(self.send_push_notifications(user, team_id, message, chat_message.id))

    async def chat_message(self, event):
        await self.send(text_data=json.dumps(event))

    @database_sync_to_async
    def send_push_notifications(self, sender, team_id, message, message_id):
        """
        Send push notifications to all team members except the sender
        """
        try:
            team = Team.objects.get(id=team_id)
            team_members = []

            # Get all coaches for the team
            coaches = Coach.objects.filter(
                Q(head_coached_teams=team) | Q(assistant_coached_teams=team)
            )
            team_members.extend([coach.user for coach in coaches])

            # Get all players for the team
            players = Player.objects.filter(team=team)
            team_members.extend([player.user for player in players])

            # Remove sender from recipients
            recipients = [user for user in team_members if user != sender]

            # Get devices for recipients
            devices = WebPushDevice.objects.filter(user__in=recipients, active=True)

            if devices.exists():
                # Send push notification
                devices.send_message(
                    title=f"{team.name}",
                    body=f"{sender.get_full_name()}: {message[:80]}{'...' if len(message) > 80 else ''}",
                    extra={
                        'team_id': team_id,
                        'message_id': message_id,
                        'sender_name': sender.get_full_name(),
                        'team_name': team.name
                    }
                )
        except Exception as e:
            print(f"Error sending push notifications: {e}")

    # -------------------------
    # DATABASE HELPERS
    # -------------------------
    @database_sync_to_async
    def get_user_profile(self, user):
        profile_data = {'profile_picture': None, 'position': None, 'jersey_number': None}
        try:
            if user.role == 'Player':
                player = Player.objects.get(user=user)
                profile_data['profile_picture'] = player.profile_picture.url if player.profile_picture else None
                profile_data['position'] = player.position
                profile_data['jersey_number'] = player.jersey_number
            elif user.role == 'Coach':
                coach = Coach.objects.get(user=user)
                profile_data['profile_picture'] = coach.profile_picture.url if coach.profile_picture else None
        except Exception:
            pass
        return profile_data

    @database_sync_to_async
    def user_can_access_team_chat(self, user, team_id):
        try:
            team = Team.objects.get(id=team_id)
            if user.is_admin:
                return True
            if user.role == 'Coach':
                coach = Coach.objects.get(user=user)
                return Team.objects.filter(Q(head_coach=coach) | Q(assistant_coach=coach), id=team.id).exists()
            if user.role == 'Player':
                player = Player.objects.get(user=user)
                return team == player.team
        except Exception:
            return False
        return False

    @database_sync_to_async
    def save_message(self, user, team_id, message):
        try:
            team = Team.objects.get(id=team_id)
            team_chat, _ = TeamChat.objects.get_or_create(team=team)
            return ChatMessage.objects.create(team_chat=team_chat, sender=user, message=message)
        except Exception:
            return None

# -------------------------
# GLOBAL CHAT CONSUMER
# -------------------------
class GlobalChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if isinstance(user, AnonymousUser):
            await self.close()
            return

        self.user = user
        self.team_groups = await self.get_user_team_groups(user)
        self.profile_cache = {}  # per connection

        for group_name in self.team_groups:
            try:
                await asyncio.wait_for(self.channel_layer.group_add(group_name, self.channel_name), timeout=2)
            except asyncio.TimeoutError:
                print(f"Timeout joining group {group_name}")

        await self.accept()
        print(f"Global chat connected for user {user.id} to teams: {self.team_groups}")

    async def disconnect(self, close_code):
        for group_name in getattr(self, 'team_groups', []):
            try:
                await asyncio.wait_for(self.channel_layer.group_discard(group_name, self.channel_name), timeout=2)
            except asyncio.TimeoutError:
                print(f"Timeout discarding group {group_name}")

    async def receive(self, text_data):
        pass  # global consumer doesn't send messages

    async def chat_message(self, event):
        # Cache sender profile
        sender_id = event['sender_id']
        if sender_id not in self.profile_cache:
            self.profile_cache[sender_id] = event.get('profile', {})
        else:
            event['profile'] = self.profile_cache[sender_id]

        await self.send(text_data=json.dumps(event))

    @database_sync_to_async
    def get_user_team_groups(self, user):
        team_ids = []
        try:
            if user.is_admin:
                team_ids = list(Team.objects.values_list('id', flat=True))
            elif user.role == 'Coach':
                coach = Coach.objects.get(user=user)
                coach_teams = Team.objects.filter(Q(head_coach=coach) | Q(assistant_coach=coach))
                team_ids = list(coach_teams.values_list('id', flat=True))
            elif user.role == 'Player':
                player = Player.objects.get(user=user)
                if player.team:
                    team_ids = [player.team.id]
        except Exception:
            pass
        return [f'chat_team_{team_id}' for team_id in team_ids]
