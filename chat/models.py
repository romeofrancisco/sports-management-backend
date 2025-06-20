from django.db import models
from django.conf import settings
from teams.models import Team

class TeamChat(models.Model):
    """
    Model to represent a chat room for each team
    """
    team = models.OneToOneField(Team, on_delete=models.CASCADE, related_name='chat_room')
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Chat Room for {self.team.name}"
    
    class Meta:
        ordering = ['-created_at']

class ChatMessage(models.Model):
    """
    Model to represent individual messages in team chats
    """
    team_chat = models.ForeignKey(TeamChat, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.sender.get_full_name()}: {self.message[:50]}..."
    
    class Meta:
        ordering = ['timestamp']
        
    def can_user_access(self, user):
        """
        Check if a user can access this message based on role and team membership
        """
        # Admin can access all messages
        if user.is_admin:
            return True
            
        # Coach can access if they coach this team
        if user.role == 'Coach':
            try:
                from teams.models import Coach
                coach = Coach.objects.get(user=user)
                return self.team_chat.team in coach.teams.all()
            except Coach.DoesNotExist:
                return False
                
        # Player can access if they're on this team
        if user.role == 'Player':
            try:
                from teams.models import Player
                player = Player.objects.get(user=user)
                return self.team_chat.team == player.team
            except Player.DoesNotExist:
                return False
                
        return False
