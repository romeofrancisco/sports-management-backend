from django.db import models
from sports.models import Sport, Position
from django.conf import settings
from django.db.models import Q, F, Max, Exists, OuterRef
from games.models import Game 
from django.utils.text import slugify
from games.models import Substitution

class TeamManager(models.Manager):
    def active(self):
        """Return only active teams"""
        return self.filter(is_active=True)
    
    def inactive(self):
        """Return only inactive teams"""
        return self.filter(is_active=False)

class Team(models.Model):
    class Division(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"
        
    name = models.CharField(max_length=100)
    abbreviation = models.CharField(max_length=5)
    color = models.CharField(max_length=20, default="#000000")
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    division = models.CharField(max_length=10, choices=Division.choices, default=Division.MALE)
    head_coach = models.ForeignKey('teams.Coach', on_delete=models.SET_NULL, null=True, blank=True, related_name='head_coached_teams')
    assistant_coach = models.ForeignKey('teams.Coach', on_delete=models.SET_NULL, null=True, blank=True, related_name='assistant_coached_teams')
    logo = models.ImageField(upload_to="team_logos/", null=True, blank=True)
    slug = models.SlugField(unique=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    objects = TeamManager()
    
    class Meta:
        ordering = ['name', 'created_at']
    
    def __str__(self):
        return f"{self.name} ({self.sport}) "
    
    def clean(self):
        from django.core.exceptions import ValidationError
        
        # Check for duplicate team names within the same sport and division
        if Team.objects.filter(
            name__iexact=self.name,
            sport=self.sport,
            division=self.division
        ).exclude(pk=self.pk).exists():
            raise ValidationError({
                'name': f"A team with the name '{self.name}' already exists in {self.sport.name} {self.division} division."
            })
    
    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        
        # Check for duplicate team names within the same sport and division
        if Team.objects.filter(
            name__iexact=self.name,
            sport=self.sport,
            division=self.division
        ).exclude(pk=self.pk).exists():
            raise ValidationError(f"A team with the name '{self.name}' already exists in {self.sport.name} {self.division} division.")
        
        # Generate unique slug
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            
            while Team.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
                
            self.slug = slug
        
        # Validate coaches can handle this sport
        if self.head_coach and not self.head_coach.can_coach_team(self):
            raise ValidationError(f"Head coach {self.head_coach} cannot coach {self.sport.name} teams.")
        
        if self.assistant_coach and not self.assistant_coach.can_coach_team(self):
            raise ValidationError(f"Assistant coach {self.assistant_coach} cannot coach {self.sport.name} teams.")
            
        try:
            super().save(*args, **kwargs)
        except Exception as e:
            # Convert any remaining integrity errors to validation errors
            if 'slug' in str(e) and 'unique constraint' in str(e):
                raise ValidationError("Team name conflicts with existing team. Please choose a different name.")
            raise e
        
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
    
    def has_associated_data(self):
        """Check if team has any associated games or training sessions"""
        # Check for games (both home and away)
        has_games = Game.objects.filter(
            Q(home_team=self) | Q(away_team=self)
        ).exists()
        
        # Check for training sessions
        from trainings.models import TrainingSession
        has_trainings = TrainingSession.objects.filter(team=self).exists()
        
        return has_games or has_trainings
    
    def soft_delete(self):
        """Soft delete the team by setting is_active to False"""
        self.is_active = False
        self.save(update_fields=['is_active'])
        return True
    
    def reactivate(self):
        """Reactivate the team by setting is_active to True"""
        self.is_active = True
        self.save(update_fields=['is_active'])
        return True
    
    def can_be_hard_deleted(self):
        """Check if team can be safely hard deleted"""
        return not self.has_associated_data()
     

class Coach(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='coach_profile',
        primary_key=True
    )
    sports = models.ManyToManyField(Sport, related_name='coaches', blank=True)
    
    class Meta:
        ordering = ['user__first_name', 'user__last_name']
    
    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name}"
    
    def can_coach_team(self, team):
        """Check if coach can coach a specific team based on their sports"""
        return self.sports.filter(id=team.sport.id).exists()
    
    def has_associated_data(self):
        """Check if coach has associated teams or other data"""
        # Check for teams where this coach is head coach or assistant coach
        has_head_coach_teams = self.head_coached_teams.exists()
        has_assistant_coach_teams = self.assistant_coached_teams.exists()
        
        return has_head_coach_teams or has_assistant_coach_teams
    
    def soft_delete(self):
        """Deactivate the coach's user account instead of deleting"""
        self.user.is_active = False
        self.user.save()
    
    def reactivate(self):
        """Reactivate the coach's user account"""
        self.user.is_active = True
        self.user.save()
    
    def can_be_hard_deleted(self):
        """Check if coach can be safely hard deleted"""
        return not self.has_associated_data()
    
    def delete(self, *args, **kwargs):
        """Override delete to also delete the associated user account"""
        user = self.user
        # First delete the coach instance
        super().delete(*args, **kwargs)
        # Then delete the user account
        if user:
            user.delete()

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
            user_id__in=subbed_out.values('substitute_out')
        )

class Player(models.Model):
    YEAR_LEVEL_CHOICES = [
        ('grade_7', 'Grade 7'),
        ('grade_8', 'Grade 8'),
        ('grade_9', 'Grade 9'),
        ('grade_10', 'Grade 10'),
        ('grade_11', 'Grade 11'),
        ('grade_12', 'Grade 12'),
        ('1st_year_college', '1st Year College'),
        ('2nd_year_college', '2nd Year College'),
        ('3rd_year_college', '3rd Year College'),
        ('4th_year_college', '4th Year College'),
    ]
    
    COURSE_CHOICES = [
        ('stem', 'STEM'),
        ('gas', 'GAS'),
        ('humss', 'HUMSS'),
        ('abm', 'ABM'),
        ('bs_cs', 'BS Computer Science'),
        ('bs_ba', 'BS Business Administration'),
    ]
        
    user = models.OneToOneField( settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='player_profile', primary_key=True)
    height = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)  # in cm
    weight = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)  # in kg
    slug = models.SlugField(max_length=255, unique=True)
    team = models.ForeignKey(Team, null=True, on_delete=models.SET_NULL, related_name="players")
    jersey_number = models.IntegerField(blank=False)
    position = models.ManyToManyField(Position, blank=True)
    sport = models.ForeignKey(Sport, null=True, on_delete=models.SET_NULL)
    year_level = models.CharField(max_length=20, choices=YEAR_LEVEL_CHOICES)
    course = models.CharField(max_length=50, choices=COURSE_CHOICES)
    
    
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
    
    def has_associated_data(self):
        """Check if player has associated games, training sessions, or other data"""
        # Check for game-related data
        has_game_stats = self.player_stats.exists()
        has_substitutions = (
            self.substitutions_in.exists() or 
            self.substitutions_out.exists()
        )
        has_lineups = hasattr(self, 'startinglineup_set') and self.startinglineup_set.exists()
        
        # Check for training-related data
        has_training_records = self.training_records.exists()
        
        return (
            has_game_stats or 
            has_substitutions or 
            has_lineups or 
            has_training_records
        )
    
    def soft_delete(self):
        """Deactivate the player's user account instead of deleting"""
        self.user.is_active = False
        self.user.save()
    
    def reactivate(self):
        """Reactivate the player's user account"""
        self.user.is_active = True
        self.user.save()
    
    def can_be_hard_deleted(self):
        """Check if player can be safely hard deleted"""
        return not self.has_associated_data()
    
    def delete(self, *args, **kwargs):
        """Override delete to also delete the associated user account"""
        user = self.user
        # First delete the player instance
        super().delete(*args, **kwargs)
        # Then delete the user account
        if user:
            user.delete()