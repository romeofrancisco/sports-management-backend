from django.db import models
import cloudinary.models
from sports.models import Sport, Position
from django.conf import settings


class Team(models.Model):
    name = models.CharField(max_length=100)
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    logo = models.ImageField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} ({self.sport}) "

class Coach(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='coach_profile',
        primary_key=True
    )
    sports = models.ManyToManyField(Sport, blank=True)
    teams = models.ManyToManyField(Team, blank=True)
    
    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name}"

class Player(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='player_profile',
        primary_key=True
    )
    height = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)  # in cm
    weight = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)  # in kg
    team = models.ForeignKey(Team, null=True, on_delete=models.SET_NULL)
    jersey_number = models.IntegerField(blank=False)
    position = models.ForeignKey(Position, null=True, on_delete=models.SET_NULL)
    sport = models.ForeignKey(Sport, null=True, on_delete=models.SET_NULL)
    
    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name}"

    class Meta:
        verbose_name = "Player Profile"
        verbose_name_plural = "Player Profiles"