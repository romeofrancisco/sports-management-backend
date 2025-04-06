from django.db import models
import cloudinary.models
from sports.models import Sport, Position
from django.conf import settings
from django.db.models import Q, F, Max, Exists, OuterRef
from games.models import Game 
from django.utils.text import slugify
from games.models import Substitution

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
        
    def win_loss_record(self):
        wins = Game.objects.filter(
            Q(home_team=self, home_team_score__gt=F('away_team_score')) |
            Q(away_team=self, away_team_score__gt=F('home_team_score')),
            status="completed"
        ).count()
        
        losses = Game.objects.filter(
            Q(home_team=self, home_team_score__lt=F('away_team_score')) |
            Q(away_team=self, away_team_score__lt=F('home_team_score')),
            status="completed"
        ).count()
        
        return wins, losses
    
    def get_record(self):
        wins, losses = self.win_loss_record()
        return {
            'win': wins,
            'loss': losses,
            'win_percentage': wins / (wins + losses) if (wins + losses) > 0 else 0
        }
     

class Coach(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='coach_profile',
        primary_key=True
    )
    
    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name}"

class PlayerManager(models.Manager):
    def active_in_game(self, game):
        """Return currently active players in the game"""
        subs = Substitution.objects.filter(game=game)
        all_players = Player.objects.filter(
            Q(team=game.home_team) | Q(team=game.away_team)
        )
        
        # Players who were subbed out without being subbed back in
        subbed_out = subs.values('substitute_out').annotate(
            last_action=Max('timestamp')
        ).filter(
            ~Exists(subs.filter(substitute_in=OuterRef('substitute_out')))
        )
        
        return all_players.exclude(
            pk__in=subbed_out.values('substitute_out')
        )

class Player(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='player_profile',
        primary_key=True
    )
    height = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)  # in cm
    weight = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)  # in kg
    slug = models.SlugField(max_length=255, unique=True)
    team = models.ForeignKey(Team, null=True, on_delete=models.SET_NULL, related_name="players")
    jersey_number = models.IntegerField(blank=False)
    position = models.ManyToManyField(Position, blank=True)
    sport = models.ForeignKey(Sport, null=True, on_delete=models.SET_NULL)
    
    objects = PlayerManager()
    
    class Meta:
        unique_together = ['team', 'jersey_number']
        
    def __str__(self):
        return f"{self.user.get_full_name()} (#{self.jersey_number})"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            # Use user's ID since it's the primary key
            base_slug = slugify(f"{self.user.first_name} {self.user.last_name}")
            self.slug = f"{base_slug}-{self.user_id}"  # user_id is the FK to User
        super().save(*args, **kwargs)
    
    def is_active_in_game(self, game):
        """Determine if player is currently on the field considering their status and substitutions"""
        # Check if player is part of the game's teams
        if self.team not in [game.home_team, game.away_team]:
            return False

        # Check if player is a starter
        is_starter = game.starting_lineup.filter(
            player=self, 
            is_starting=True
        ).exists()

        # Get substitution counts
        subs_out = self.substitutions_out.filter(game=game).count()
        subs_in = self.substitutions_in.filter(game=game).count()

        # Determine active status
        if is_starter:
            # Starter is active if not subbed out more than subbed back in
            return subs_out <= subs_in
        else:
            # Substitute is active if subbed in more than subbed out
            return subs_in > subs_out