from django.db import models
from django.utils.text import slugify


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
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = f"{slugify(self.name)}-{self.id}"
        super().save(*args, **kwargs)


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


class SportStatType(models.Model):
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    name = models.CharField(max_length=30)
    display_name = models.CharField(
        null=True,
        blank=True,
        max_length=15,
        help_text="Displayed name for metrics",
    )
    code = models.CharField(max_length=20, blank=True, null=True)
    point_value = models.IntegerField(default=0)
    is_team_summary = models.BooleanField(default=False)
    is_player_summary = models.BooleanField(default=False)
    is_record = models.BooleanField(default=False)
    is_counter = models.BooleanField(default=False)
    is_box_score = models.BooleanField(default=False)
    formula = models.ForeignKey(
        Formula,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Formula to calculate this stat",
    )
    is_negative = models.BooleanField(default=False)

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
