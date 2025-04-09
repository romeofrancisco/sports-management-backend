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
    max_players_per_team = models.PositiveIntegerField(blank=False)
    max_players_on_field = models.PositiveIntegerField(blank=False)
    has_period = models.BooleanField(default=False)
    max_period = models.PositiveIntegerField(
        blank=True, null=True, help_text="Maximum periods/quarters/sets possible"
    )
    has_tie = models.BooleanField(default=False)
    win_threshold = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Target value needed to win a match (e.g., 3 sets, 25 points)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = f"{slugify(self.name)}-{self.id}"
        super().save(*args, **kwargs)


class SportStatType(models.Model):
    class CALULATION_TYPE(models.TextChoices):
        NONE = "none", "None"
        SUM = "sum", "Sum"
        PERCENTAGE = "percentage", "Percentage"

    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    abbreviation = models.CharField(max_length=10, blank=True, null=True)
    point_value = models.IntegerField(default=0)
    is_counter = models.BooleanField(default=False)
    calculation_type = models.CharField(
        max_length=20, choices=CALULATION_TYPE.choices, default="none"
    )
    is_negative = models.BooleanField(default=False)
    related_stat = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="counterpart_stats",
    )
    composite_stats = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="component_of_stats"
    )

    class Meta:
        unique_together = ["sport", "name"]

    def __str__(self):
        return self.name

    def get_opposite_stat(self):
        return (
            self.related_stat or SportStatType.objects.filter(related_stat=self).first()
        )

    def get_all_base_components(self):
        components = set()
        for component in self.composite_stats.all():
            if component.composite_stats.exists():
                components.update(component.get_all_base_components())
            else:
                components.add(component)
        return components


class Position(models.Model):
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    abbreviation = models.CharField(max_length=3, blank=True)

    def __str__(self):
        return f"{self.name} ({self.sport})"
