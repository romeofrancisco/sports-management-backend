from django.db import models
from django.utils.text import slugify
from django.core.exceptions import ValidationError


class ActiveSportManager(models.Manager):
    """Manager to return only active sports by default"""
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class Sport(models.Model):
    class SCORING_TYPES(models.TextChoices):
        POINTS = "points", "Points"
        SETS = "sets", "Sets"

    scoring_type = models.CharField(
        max_length=20, choices=SCORING_TYPES, default="points"
    )
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    banner = models.ImageField(upload_to="sport_banner/", null=True, blank=True)
    max_players_per_team = models.PositiveIntegerField(
        default=12,  # Add default value
        help_text="Maximum players allowed per team roster",
    )
    max_players_on_field = models.PositiveIntegerField(
        default=5,  # Add default value
        help_text="Maximum players allowed on the field/court during play",
    )
    has_period = models.BooleanField(default=False)
    max_period = models.PositiveIntegerField(
        blank=True, null=True, help_text="Maximum periods/quarters/sets possible"
    )
    has_tie = models.BooleanField(default=False)
    has_overtime = models.BooleanField(default=False)

    # Sets
    win_threshold = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Target value needed to win a match (e.g., 3 sets)",
    )
    win_points_threshold = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Target points needed to win a match (e.g., 3 sets)",
    )
    win_margin = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Target value needed to win a match (e.g., 3 sets)",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this sport is active and can be used for new games"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Managers
    objects = models.Manager()  # Default manager (includes inactive)
    active = ActiveSportManager()  # Active sports only

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = f"{slugify(self.name)}-{self.id}"
        super().save(*args, **kwargs)

    def soft_delete(self):
        """
        Soft delete the sport by setting is_active to False
        This preserves historical data while preventing new usage
        """
        if self.has_associated_data():
            self.is_active = False
            self.save(update_fields=['is_active'])
            return True
        return False

    def reactivate(self):
        """Reactivate a soft-deleted sport"""
        self.is_active = True
        self.save(update_fields=['is_active'])

    def has_associated_data(self):
        """
        Check if this sport has any associated data that would prevent hard deletion
        """
        # Check for games
        if hasattr(self, 'game_set') and self.game_set.exists():
            return True
        
        # Check for teams
        if hasattr(self, 'team_set') and self.team_set.exists():
            return True
            
        # Check for leagues
        if hasattr(self, 'league_set') and self.league_set.exists():
            return True
            
        # Check for stat types
        if self.sportstattype_set.exists():
            return True
            
        return False

    def can_hard_delete(self):
        """
        Check if this sport can be safely hard deleted
        (has no associated data)
        """
        return not self.has_associated_data()

    @property
    def status_display(self):
        """Display status for admin interface"""
        return "Active" if self.is_active else "Inactive"


class Formula(models.Model):
    name = models.CharField(max_length=100)
    expression = models.TextField(
        help_text="Python formula using component codes as variables",
        null=True,
        blank=True,
    )
    is_ratio = models.BooleanField(
        default=False, help_text="Is this formula a ratio (e.g., made/attempt)?"
    )
    uses_point_value = models.BooleanField(
        default=False, help_text="If True, uses stat_type.point_value in calculations instead of count"
    )
    decimal_places = models.PositiveSmallIntegerField(
        default=3,
        help_text="Number of decimal places to round the result to"
    )
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.name} - {self.expression}"


class FormulaComponent(models.Model):
    formula = models.ForeignKey(
        Formula, on_delete=models.CASCADE, related_name="components"
    )
    stat_type = models.ForeignKey("sports.SportStatType", on_delete=models.CASCADE)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.formula.name} - {self.stat_type.name} ({self.order})"
    
class SportStatCategory(models.Model):
    name = models.CharField(max_length=100)
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.name} - {self.sport.name}"

class SportStatType(models.Model):
    class CATEGORY_TYPES(models.TextChoices):
        SCORING = "scoring", "Scoring"
        PERFORMANCE = "performance", "Performance"
        OFFENSIVE = "offensive", "Offensive"
        DEFENSIVE = "defensive", "Defensive"
        OTHER = "other", "Other"
    
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE, help_text="The sport this stat type belongs to")
    name = models.CharField(max_length=30, help_text="Name of the stat type (e.g. 'Field Goal', 'Assists')")
    display_name = models.CharField(
        null=True,
        blank=True,
        max_length=15,
        help_text="Shortened display name for UI elements",
    )
    code = models.CharField(max_length=20, blank=True, null=True, help_text="Code used in formulas (e.g. 'FG', 'AST')")
    point_value = models.IntegerField(default=0, help_text="Points awarded for this stat (0 if not a scoring stat)")
    category = models.CharField(
        max_length=20, 
        choices=CATEGORY_TYPES, 
        default=CATEGORY_TYPES.OTHER,
        help_text="Category for organizing stats in the UI",
        null=True,
    )
    
    is_team_summary = models.BooleanField(default=False, help_text="If True, this stat appears in team summary statistics")
    is_player_summary = models.BooleanField(default=False, help_text="If True, this stat appears in player summary statistics")
    
    is_team_comparison = models.BooleanField(default=False, help_text="If True, this stat is used when comparing teams")
    
    is_record = models.BooleanField(default=False, help_text="If True, this stat can be recorded during games")
    is_points = models.BooleanField(default=False, help_text="If True, this stat is a scoring stat that contributes points")
    is_boxscore = models.BooleanField(default=False, help_text="If True, this stat appears in the game boxscore")
        
    formula = models.ForeignKey(
        Formula,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Formula to calculate this stat",
    )
    is_negative = models.BooleanField(default=False, help_text="If True, this stat represents a negative action (like turnovers)")

    class Meta:
        ordering = ["name"]
        unique_together = ["sport", "name", "is_record"]

    def __str__(self):
        return f"{self.name} - {self.code}"


class Position(models.Model):
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    abbreviation = models.CharField(max_length=10, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sport", "name"], name="unique_position_name_per_sport"
            ),
            models.UniqueConstraint(
                fields=["sport", "abbreviation"], name="unique_position_abbr_per_sport"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.sport})"


class LeaderCategory(models.Model):
    """
    Model for defining leader categories in games and seasons
    Examples: Points, Rebounds, Assists, Blocks, etc.
    """
    
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE, related_name='leader_categories',
                             help_text="The sport this leader category belongs to")
    name = models.CharField(max_length=50, help_text="Name of the leader category")
    display_order = models.PositiveSmallIntegerField(default=0, 
                                                  help_text="Order for displaying the category in UI")
    stat_types = models.ManyToManyField(SportStatType, related_name='leader_categories',
                                help_text="Stats used to determine leaders (max 4)")
    primary_stat = models.ForeignKey(
        SportStatType, 
        on_delete=models.CASCADE, 
        related_name='primary_for_categories',
        null=True,
        blank=True,
        help_text="The primary stat used for ordering leaders in this category"
    )
    
    class Meta:
        ordering = ['display_order', 'name']
        unique_together = ['sport', 'name']
        verbose_name = "Leader Category"
        verbose_name_plural = "Leader Categories"
        
    def __str__(self):
        return f"{self.name} - {self.sport.name}"
    
    def clean(self):
        """Validate that there are at most 8 categories per sport"""
        categories = LeaderCategory.objects.filter(sport=self.sport)
        
        # Exclude self when checking for updates
        if self.pk:
            categories = categories.exclude(pk=self.pk)
        
        # Allow up to 8 categories per sport
        if categories.count() >= 8:
            raise ValidationError({"leader_category": "Maximum of 8 leader categories per sport allowed."})
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
        
        # We'll handle the stat_types validation in the serializer instead
        # This avoids issues with M2M relationships not being set yet during save()
