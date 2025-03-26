from django.db import models
import cloudinary.models
from sports.models import Sport, Position
from django.conf import settings
from django.db.models import Q, F, Count, Case, When, IntegerField
from games.models import Game 
from django.utils.text import slugify
from django.core.exceptions import ValidationError

class Team(models.Model):
    name = models.CharField(max_length=100)
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    coach = models.ManyToManyField('teams.Coach', blank=True)
    logo = models.ImageField(upload_to="team_logos/", null=True, blank=True)
    slug = models.SlugField(unique=True, blank=True)  
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} ({self.sport}) "
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)  # Auto-generate slug from name
        super().save(*args, **kwargs)
        
    def record(self):
        record = Game.objects.filter(status="completed").aggregate(
            wins=Count(
                Case(
                    When(
                        Q(home_team=self, home_team_score__gt=F("away_team_score")) |
                        Q(away_team=self, away_team_score__gt=F("home_team_score")),
                        then=1,
                    ),
                    output_field=IntegerField(),
                )
            ),
            losses=Count(
                Case(
                    When(
                        Q(home_team=self, home_team_score__lt=F("away_team_score")) |
                        Q(away_team=self, away_team_score__lt=F("home_team_score")),
                        then=1,
                    ),
                    output_field=IntegerField(),
                )
            ),
        )

        return record["wins"], record["losses"]
     

class Coach(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='coach_profile',
        primary_key=True
    )
    
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
    team = models.ForeignKey(Team, null=True, blank=False, on_delete=models.SET_NULL, related_name="players")
    jersey_number = models.IntegerField(blank=False)
    position = models.ManyToManyField(Position, blank=False, related_name="positions")
    sport = models.ForeignKey(Sport, blank=False, null=True, on_delete=models.SET_NULL)
    slug = models.SlugField(unique=True, blank=True)
    
    REQUIRED_FIELDS = ["team", "jersey_number", "position", "sport"]
    
    def clean(self):
        super().clean()
        errors = {}
        if self.height is not None and self.height <= 0:
            errors['height'] = "Height must be a positive number."
        if self.weight is not None and self.weight <= 0:
            errors['weight'] = "Weight must be a positive number."
        if self.jersey_number <= 0:
            errors['jersey_number'] = "Jersey number must be a positive integer."
        if not self.sport:
            errors['sport'] = "A sport must be selected for the player."
        if not self.team:
            errors['team'] = "A team must be associated with the player."
        if errors:
            raise ValidationError(errors)
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f"{self.user.first_name}-{self.user.last_name}-{self.user.id}")
        self.full_clean()
        super().save(*args, **kwargs)
    
    
    def delete(self, *args, **kwargs):
        """Delete the associated user when the player instance is deleted."""
        user = self.user  # Store reference to user before deleting Player
        super().delete(*args, **kwargs)  # Delete Player instance
        if user:
            user.delete()  # Delete User instance

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name}"

    class Meta:
        verbose_name = "Player Profile"
        verbose_name_plural = "Player Profiles"