from django.shortcuts import render
from rest_framework import generics, permissions, status, serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q
from push_notifications.models import WebPushDevice
from .models import TeamChat, ChatMessage
from .serializers import TeamChatSerializer, ChatMessageSerializer
from teams.models import Team, Coach, Player

class ChatMessagePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

class TeamChatListView(generics.ListAPIView):
    serializer_class = TeamChatSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        
        # Admin can see all team chats
        if user.is_admin:
            return TeamChat.objects.all()
              # Coach can see chats for teams they coach
        if user.role == 'Coach':
            try:
                coach = Coach.objects.get(user=user)
                from django.db.models import Q
                from teams.models import Team
                coach_teams = Team.objects.filter(
                    Q(head_coach=coach) | Q(assistant_coach=coach)
                )
                team_ids = coach_teams.values_list('id', flat=True)
                return TeamChat.objects.filter(team__id__in=team_ids)
            except Coach.DoesNotExist:
                return TeamChat.objects.none()
                
        # Player can see chat for their team only
        if user.role == 'Player':
            try:
                player = Player.objects.get(user=user)
                return TeamChat.objects.filter(team=player.team)
            except Player.DoesNotExist:
                return TeamChat.objects.none()
                
        return TeamChat.objects.none()

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
            
        # Check if user can access this team's chat
        if not self.user_can_access_team_chat(user, team):
            return ChatMessage.objects.none()
            
        team_chat, created = TeamChat.objects.get_or_create(team=team)
        return team_chat.messages.all().order_by('-timestamp')
    
    def perform_create(self, serializer):
        team_id = self.kwargs.get('team_id')
        try:
            team = Team.objects.get(id=team_id)
            if self.user_can_access_team_chat(self.request.user, team):
                team_chat, created = TeamChat.objects.get_or_create(team=team)
                serializer.save(team_chat=team_chat, sender=self.request.user)
            else:
                raise permissions.PermissionDenied("You don't have permission to send messages to this team.")
        except Team.DoesNotExist:
            raise serializers.ValidationError("Team not found.")
    
    def user_can_access_team_chat(self, user, team):
        """
        Check if user can access this team chat based on their role
        """
        # Admin can access all team chats
        if user.is_admin:
            return True
              # Coach can access if they coach this team
        if user.role == 'Coach':
            try:
                coach = Coach.objects.get(user=user)
                from django.db.models import Q
                from teams.models import Team
                return Team.objects.filter(
                    Q(head_coach=coach) | Q(assistant_coach=coach),
                    id=team.id
                ).exists()
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

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def mark_messages_as_read(request, team_id):
    """
    Mark messages as read for the current user in a specific team chat
    """
    try:
        team = Team.objects.get(id=team_id)
        team_chat = TeamChat.objects.get(team=team)
        
        # Update unread messages to read for this user
        ChatMessage.objects.filter(
            team_chat=team_chat,
            is_read=False
        ).exclude(sender=request.user).update(is_read=True)
        
        return Response({'status': 'Messages marked as read'}, status=status.HTTP_200_OK)
    except (Team.DoesNotExist, TeamChat.DoesNotExist):
        return Response({'error': 'Team or chat not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_vapid_public_key(request):
    """
    Get the VAPID public key for push notifications
    """
    from django.conf import settings
    vapid_public_key = getattr(settings, 'PUSH_NOTIFICATIONS_SETTINGS', {}).get('VAPID_PUBLIC_KEY')
    if vapid_public_key:
        return Response({'public_key': vapid_public_key})
    else:
        return Response({'error': 'VAPID public key not configured'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def subscribe_to_push(request):
    """
    Subscribe a user to push notifications
    """
    subscription_data = request.data.get('subscription')
    user_id = request.data.get('user_id')

    if not subscription_data or not user_id:
        return Response({'error': 'Subscription data and user_id are required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Create or update the device
        device, created = WebPushDevice.objects.get_or_create(
            user_id=user_id,
            defaults={
                'registration_id': subscription_data.get('endpoint'),
                'p256dh': subscription_data.get('keys', {}).get('p256dh'),
                'auth': subscription_data.get('keys', {}).get('auth'),
                'browser': 'CHROME',  # Assuming web push
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
