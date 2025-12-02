from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class FCMDevice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    fcm_token = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'fcm_token')
        indexes = [
            models.Index(fields=['user', 'fcm_token']),
        ]


class NotificationLog(models.Model):
    """Model to track all notifications sent to users."""
    
    class NotificationType(models.TextChoices):
        EVENT = 'event', 'Event'
        LEAGUE_GAME = 'league_game', 'League Game'
        TOURNAMENT_GAME = 'tournament_game', 'Tournament Game'
        PRACTICE_GAME = 'practice_game', 'Practice Game'
        BULK_GAMES = 'bulk_games', 'Bulk Games'
        TRAINING = 'training', 'Training Session'
        FACILITY = 'facility', 'Facility Reservation'
        FACILITY_STATUS = 'facility_status', 'Facility Reservation Status'
        CHAT = 'chat', 'Chat Message'
    
    class ActionType(models.TextChoices):
        CREATED = 'created', 'Created'
        UPDATED = 'updated', 'Updated'
        STATUS_CHANGE = 'status_change', 'Status Change'
    
    recipient = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='notification_logs'
    )
    notification_type = models.CharField(
        max_length=20, 
        choices=NotificationType.choices
    )
    action_type = models.CharField(
        max_length=20, 
        choices=ActionType.choices,
        default=ActionType.CREATED
    )
    title = models.CharField(max_length=255)
    body = models.TextField()
    
    # Reference to the related object (generic approach)
    # Using CharField to support both integer IDs and UUIDs
    related_object_id = models.CharField(max_length=100, null=True, blank=True)
    related_object_type = models.CharField(max_length=50, null=True, blank=True)
    
    # Additional data stored as JSON-like text
    click_action = models.URLField(max_length=500, null=True, blank=True)
    
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', '-created_at']),
            models.Index(fields=['notification_type']),
            models.Index(fields=['is_read']),
        ]
    
    def __str__(self):
        return f"{self.notification_type} - {self.title} - {self.recipient.get_full_name()}"
