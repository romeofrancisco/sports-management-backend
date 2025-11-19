from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class FCMDevice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    fcm_token = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
