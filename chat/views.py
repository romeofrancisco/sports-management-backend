# chat/views.py
from rest_framework import generics, permissions, status, serializers
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from .models import TeamChat, ChatMessage
from .serializers import TeamChatSerializer, ChatMessageSerializer
from teams.models import Team, Coach, Player
from django.db.models import Q
from notifications.utils import send_web_push
import asyncio

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

        # Send push notifications asynchronously
        asyncio.create_task(
            send_web_push(user, team_id, message.message, message.id, team.name)
        )

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
