from rest_framework import serializers
from .models import TeamChat, ChatMessage
from teams.models import Team
from users.models import User

class ChatMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source='sender.get_full_name', read_only=True)
    sender_role = serializers.CharField(source='sender.role', read_only=True)
    sender_id = serializers.IntegerField(source='sender.id', read_only=True)
    sender_profile = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = ChatMessage
        fields = ['id', 'message', 'timestamp', 'sender_name', 'sender_role', 'sender_id', 'sender_profile', 'is_read']
        read_only_fields = ['id', 'timestamp', 'sender_name', 'sender_role', 'sender_id', 'sender_profile']

    def get_sender_profile(self, obj):
        user = obj.sender
        profile_url = None
        if hasattr(user, 'profile') and user.profile:
            request = self.context.get('request')
            if request:
                profile_url = request.build_absolute_uri(user.profile.url)
            else:
                profile_url = user.profile.url
        return profile_url

class TeamChatSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source='team.name', read_only=True)
    team_id = serializers.IntegerField(source='team.id', read_only=True)
    logo = serializers.SerializerMethodField(read_only=True)
    latest_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    
    class Meta:
        model = TeamChat
        fields = ['id', 'team_name', 'team_id', 'logo', 'created_at', 'latest_message', 'unread_count']
        
    def get_latest_message(self, obj):
        latest = obj.messages.last()
        if latest:
            # Pass context to nested serializer for absolute URLs
            return ChatMessageSerializer(latest, context=self.context).data
        return None
        
    def get_unread_count(self, obj):
        user = self.context.get('request').user if self.context.get('request') else None
        if user:
            return obj.messages.filter(is_read=False).exclude(sender=user).count()
        return 0
    
    def get_logo(self, obj):
        request = self.context.get('request', None)
        logo = getattr(obj.team, 'logo', None)
        if logo:
            if request:
                return request.build_absolute_uri(logo.url)
            return logo.url
        return None
