# chat/views.py
from rest_framework import generics, permissions, status, serializers
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from .models import TeamChat, ChatMessage
from .serializers import TeamChatSerializer, ChatMessageSerializer
from teams.models import Team, Coach, Player
from django.db.models import Q
from notifications.models import FCMDevice
from django.db import transaction

# -------------------------
# PAGINATION
# -------------------------
class ChatMessagePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

# -------------------------
# LIST ALL TEAM CHATS
# -------------------------
class TeamChatListView(generics.ListAPIView):
    serializer_class = TeamChatSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        # Admin sees all team chats
        if user.is_admin:
            return TeamChat.objects.all()

        # Coaches see chats for teams they coach
        if user.role == 'Coach':
            try:
                coach = Coach.objects.get(user=user)
                return TeamChat.objects.filter(
                    Q(team__head_coach=coach) | Q(team__assistant_coach=coach)
                )
            except Coach.DoesNotExist:
                return TeamChat.objects.none()

        # Players see chat for their team only
        if user.role == 'Player':
            try:
                player = Player.objects.get(user=user)
                return TeamChat.objects.filter(team=player.team)
            except Player.DoesNotExist:
                return TeamChat.objects.none()

        return TeamChat.objects.none()

# -------------------------
# TEAM CHAT MESSAGES
# -------------------------
class TeamChatMessagesView(generics.ListCreateAPIView):
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ChatMessagePagination

    def get_queryset(self):
        team_id = self.kwargs.get('team_id')
        user = self.request.user

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return ChatMessage.objects.none()

        if not self.user_can_access_team_chat(user, team):
            return ChatMessage.objects.none()

        team_chat, _ = TeamChat.objects.get_or_create(team=team)
        return team_chat.messages.all().order_by('-timestamp')

    def perform_create(self, serializer):
        team_id = self.kwargs.get('team_id')
        user = self.request.user

        team = Team.objects.get(id=team_id)
        if not self.user_can_access_team_chat(user, team):
            raise permissions.PermissionDenied("No access to this team's chat.")

        team_chat, _ = TeamChat.objects.get_or_create(team=team)
        message = serializer.save(team_chat=team_chat, sender=user)

        # Disable Web Push - using FCM only
        # asyncio.create_task(
        #     send_web_push(user, team_id, message.message, message.id, team.name)
        # )

    def user_can_access_team_chat(self, user, team):
        if user.is_admin:
            return True

        if user.role == 'Coach':
            try:
                coach = Coach.objects.get(user=user)
                return Team.objects.filter(Q(head_coach=coach) | Q(assistant_coach=coach), id=team.id).exists()
            except Coach.DoesNotExist:
                return False

        if user.role == 'Player':
            try:
                player = Player.objects.get(user=user)
                return team == player.team
            except Player.DoesNotExist:
                return False

        return False

# -------------------------
# MARK MESSAGES AS READ
# -------------------------
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def mark_messages_as_read(request, team_id):
    try:
        team = Team.objects.get(id=team_id)
        team_chat = TeamChat.objects.get(team=team)

        ChatMessage.objects.filter(
            team_chat=team_chat,
            is_read=False
        ).exclude(sender=request.user).update(is_read=True)

        return Response({'status': 'Messages marked as read'}, status=status.HTTP_200_OK)
    except (Team.DoesNotExist, TeamChat.DoesNotExist):
        return Response({'error': 'Team or chat not found'}, status=status.HTTP_404_NOT_FOUND)

# -------------------------
# GET VAPID PUBLIC KEY
# -------------------------
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_vapid_public_key(request):
    from django.conf import settings
    vapid_public_key = getattr(settings, 'PUSH_NOTIFICATIONS_SETTINGS', {}).get('VAPID_PUBLIC_KEY')
    if vapid_public_key:
        return Response({'public_key': vapid_public_key})
    return Response({'error': 'VAPID public key not configured'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# -------------------------
# SUBSCRIBE TO PUSH NOTIFICATIONS
# -------------------------
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def subscribe_to_push(request):
    from push_notifications.models import WebPushDevice

    subscription_data = request.data.get('subscription')
    user_id = request.data.get('user_id')

    if not subscription_data or not user_id:
        return Response({'error': 'Subscription data and user_id are required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        device, created = WebPushDevice.objects.get_or_create(
            user_id=user_id,
            defaults={
                'registration_id': subscription_data.get('endpoint'),
                'p256dh': subscription_data.get('keys', {}).get('p256dh'),
                'auth': subscription_data.get('keys', {}).get('auth'),
                'browser': 'CHROME',
            }
        )

        if not created:
            device.registration_id = subscription_data.get('endpoint')
            device.p256dh = subscription_data.get('keys', {}).get('p256dh')
            device.auth = subscription_data.get('keys', {}).get('auth')
            device.save()

        return Response({'status': 'Subscribed successfully'}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# -------------------------
# SAVE FCM TOKEN
# -------------------------
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def save_fcm_token(request):
    """Save or update FCM token for a user. Each browser/device gets its own token."""
    from django.db import IntegrityError, transaction
    
    token = request.data.get('token')
    user = request.user

    if not token:
        return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        with transaction.atomic():
            # Use filter to handle potential duplicates in the database
            existing_devices = FCMDevice.objects.filter(fcm_token=token)
            device_count = existing_devices.count()
            
            if device_count == 0:
                # No existing device, create new one
                FCMDevice.objects.create(user=user, fcm_token=token)
                print(f"[FCM] Token created for user {user.id}: {token[:30]}...")
                action = 'created'
            elif device_count == 1:
                # Exactly one device exists
                device = existing_devices.first()
                if device.user_id != user.id:
                    device.user = user
                    device.save(update_fields=['user'])
                    print(f"[FCM] Token reassigned to user {user.id}")
                    action = 'reassigned'
                else:
                    action = 'already exists'
            else:
                # Multiple duplicates exist - clean them up, keep one
                print(f"[FCM] Found {device_count} duplicate tokens, cleaning up...")
                # Keep the first one, delete the rest
                device_to_keep = existing_devices.first()
                device_to_keep.user = user
                device_to_keep.save(update_fields=['user'])
                # Delete duplicates
                existing_devices.exclude(pk=device_to_keep.pk).delete()
                action = 'deduplicated'
        
        return Response({
            'status': f'FCM token {action}',
            'token': token
        }, status=status.HTTP_200_OK)
        
    except IntegrityError as e:
        # Race condition - token was created by another request
        print(f"[FCM] IntegrityError (race condition): {e}")
        return Response({
            'status': 'FCM token already registered',
            'token': token
        }, status=status.HTTP_200_OK)
    except Exception as e:
        print(f"[FCM] Unexpected error saving token: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# -------------------------
# BROADCAST MESSAGE TO MULTIPLE TEAMS
# -------------------------
class BroadcastMessageView(APIView):
    """
    Allows admins to broadcast a message to all teams,
    and coaches to broadcast to teams they handle.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_accessible_teams(self, user):
        """Get teams the user can broadcast to."""
        if user.is_admin:
            return Team.objects.all()
        
        if user.role == 'Coach':
            try:
                coach = Coach.objects.get(user=user)
                return Team.objects.filter(
                    Q(head_coach=coach) | Q(assistant_coach=coach)
                )
            except Coach.DoesNotExist:
                return Team.objects.none()
        
        return Team.objects.none()

    def get(self, request):
        """Get list of teams that the user can broadcast to."""
        teams = self.get_accessible_teams(request.user)
        
        team_list = [
            {
                'id': team.id,
                'name': team.name,
                'logo': request.build_absolute_uri(team.logo.url) if team.logo else None,
            }
            for team in teams
        ]
        
        return Response({
            'teams': team_list,
            'can_broadcast_all': request.user.is_admin,
        })

    def post(self, request):
        """Broadcast a message to selected teams."""
        message_text = request.data.get('message', '').strip()
        team_ids = request.data.get('team_ids', [])
        broadcast_all = request.data.get('broadcast_all', False)
        
        if not message_text:
            return Response(
                {'error': 'Message is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        user = request.user
        accessible_teams = self.get_accessible_teams(user)
        
        # Determine target teams
        if broadcast_all and user.is_admin:
            target_teams = accessible_teams
        elif team_ids:
            # Filter to only accessible teams
            target_teams = accessible_teams.filter(id__in=team_ids)
        else:
            return Response(
                {'error': 'No teams selected for broadcast'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not target_teams.exists():
            return Response(
                {'error': 'No valid teams to broadcast to'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        created_messages = []
        failed_teams = []
        
        with transaction.atomic():
            for team in target_teams:
                try:
                    team_chat, _ = TeamChat.objects.get_or_create(team=team)
                    message = ChatMessage.objects.create(
                        team_chat=team_chat,
                        sender=user,
                        message=message_text
                    )
                    created_messages.append({
                        'team_id': team.id,
                        'team_name': team.name,
                        'message_id': message.id
                    })
                except Exception as e:
                    failed_teams.append({
                        'team_id': team.id,
                        'team_name': team.name,
                        'error': str(e)
                    })
        
        return Response({
            'status': 'Broadcast sent',
            'successful': len(created_messages),
            'failed': len(failed_teams),
            'messages': created_messages,
            'errors': failed_teams if failed_teams else None
        }, status=status.HTTP_201_CREATED)
