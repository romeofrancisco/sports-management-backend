import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.db.models import Q
from teams.models import Team, Coach, Player
from .models import TeamChat, ChatMessage
from notifications.utils import send_fcm_notification


class TeamChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.team_id = self.scope['url_route']['kwargs']['team_id']
        self.room_group_name = f'chat_team_{self.team_id}'
        self.profile_cache = {}

        user = self.scope["user"]
        if isinstance(user, AnonymousUser) or not await self.user_can_access_team_chat(user, self.team_id):
            await self.close()
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message = data['message']
            user = self.scope["user"]
            await self.save_and_broadcast(user, self.team_id, message)
        except Exception as e:
            await self.send(json.dumps({'error': str(e)}))

    async def save_and_broadcast(self, user, team_id, message):
        chat_message = await self.save_message(user, team_id, message)
        if not chat_message:
            return

        team = await database_sync_to_async(Team.objects.get)(id=team_id)
        profile_info = self.profile_cache.get(user.id) or await self.get_user_profile(user)
        self.profile_cache[user.id] = profile_info

        event = {
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

        # Broadcast to channel group
        await self.channel_layer.group_send(self.room_group_name, event)

        # Push notifications asynchronously via FCM
        asyncio.create_task(self.push_notifications(user, team, message, chat_message.id))

    async def chat_message(self, event):
        await self.send(json.dumps(event))

    @database_sync_to_async
    def push_notifications(self, sender, team, message, message_id):
        """Send FCM notifications to all team members except sender"""
        try:
            send_fcm_notification(sender, team.id, message, message_id, team.name)
        except Exception as e:
            print(f"FCM push error: {e}")

    # --- Helpers ---
    @database_sync_to_async
    def get_user_profile(self, user):
        data = {'profile_picture': None, 'position': None, 'jersey_number': None}
        try:
            if user.role == 'Player':
                p = Player.objects.get(user=user)
                data.update({
                    'profile_picture': p.profile_picture.url if p.profile_picture else None,
                    'position': p.position,
                    'jersey_number': p.jersey_number
                })
            elif user.role == 'Coach':
                c = Coach.objects.get(user=user)
                data['profile_picture'] = c.profile_picture.url if c.profile_picture else None
        except Exception:
            pass
        return data

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
        self.user = self.scope["user"]
        if isinstance(self.user, AnonymousUser):
            await self.close()
            return

        self.team_groups = await self.get_user_team_groups(self.user)
        self.profile_cache = {}

        for group_name in self.team_groups:
            try:
                await asyncio.wait_for(
                    self.channel_layer.group_add(group_name, self.channel_name),
                    timeout=2
                )
            except asyncio.TimeoutError:
                print(f"Timeout joining group {group_name}")

        await self.accept()
        print(f"Global chat connected for user {self.user.id} to teams: {self.team_groups}")

    async def disconnect(self, close_code):
        for group_name in getattr(self, 'team_groups', []):
            try:
                await asyncio.wait_for(
                    self.channel_layer.group_discard(group_name, self.channel_name),
                    timeout=2
                )
            except asyncio.TimeoutError:
                print(f"Timeout discarding group {group_name}")

    async def receive(self, text_data):
        """Only admin can send global announcements"""
        try:
            data = json.loads(text_data)
            message = data.get('message')
            if not message:
                return

            if not self.user.is_admin:
                await self.send(json.dumps({'error': 'Only admin can send global messages'}))
                return

            for group_name in self.team_groups:
                await self.channel_layer.group_send(
                    group_name,
                    {
                        'type': 'chat_message',
                        'team_id': group_name.split("_")[-1],
                        'team_name': "Global Announcement",
                        'message': message,
                        'sender_name': self.user.get_full_name(),
                        'sender_id': self.user.id,
                        'sender_role': self.user.role,
                        'profile': {},
                        'timestamp': None,
                        'message_id': None
                    }
                )

            asyncio.create_task(self.send_global_push(message))

        except Exception as e:
            await self.send(json.dumps({'error': str(e)}))

    async def chat_message(self, event):
        sender_id = event.get('sender_id')
        if sender_id and sender_id not in self.profile_cache:
            self.profile_cache[sender_id] = event.get('profile', {})
        else:
            event['profile'] = self.profile_cache.get(sender_id, {})

        await self.send(text_data=json.dumps(event))

    # -------------------------
    # HELPERS
    # -------------------------
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

    @database_sync_to_async
    def send_global_push(self, message):
        try:
            from notifications.models import FCMDevice
            import firebase_admin
            from firebase_admin import messaging
            
            recipients = []
            for group_name in self.team_groups:
                team_id = int(group_name.split("_")[-1])
                team = Team.objects.get(id=team_id)

                coaches = Coach.objects.filter(Q(head_coached_teams=team) | Q(assistant_coached_teams=team))
                recipients.extend([c.user for c in coaches])

                players = Player.objects.filter(team=team)
                recipients.extend([p.user for p in players])

            recipients = [u for u in set(recipients) if u != self.user]
            devices = FCMDevice.objects.filter(user__in=recipients)

            if devices.exists():
                success_count = 0
                for device in devices:
                    try:
                        # Send data-only message - service worker will create the notification
                        fcm_message = messaging.Message(
                            data={
                                "title": "Global Announcement",
                                "body": message,
                                "click_action": "/chat"
                            },
                            token=device.fcm_token,
                        )
                        messaging.send(fcm_message)
                        success_count += 1
                    except Exception as e:
                        print(f"✗ Error sending global FCM to user {device.user.id}: {e}")
                print(f"✓ Sent {success_count} global FCM notifications")
        except Exception as e:
            print(f"FCM global push error: {e}")


