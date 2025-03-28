from django.db import models
from django.utils.text import slugify

class Sport(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, blank=True)  
    max_players_per_team = models.PositiveIntegerField(blank=False)
    max_players_on_field = models.PositiveIntegerField(blank=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)  # Auto-generate slug from name
        super().save(*args, **kwargs)

class SportStatType(models.Model):
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    abbreviation = models.CharField(max_length=10, blank=True, null=True)
    point_value = models.IntegerField(default=0)
    is_counter = models.BooleanField(default=False)
    is_negative = models.BooleanField(default=False)
    related_stat = models.ForeignKey('self', 
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='counterpart_stats'
    )
    composite_stats = models.ManyToManyField(
        'self',
        symmetrical=False,
        blank=True,
        related_name='component_of_stats'
    )

    class Meta:
        unique_together = ['sport', 'name']
        
    def __str__(self):
        return self.name

    def get_opposite_stat(self):
        return self.related_stat or SportStatType.objects.filter(
            related_stat=self
        ).first()


class Position(models.Model):
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    abbreviation = models.CharField(max_length=3, blank=True)

    def __str__(self):
        return f"{self.name} ({self.sport})"
