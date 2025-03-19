from django.db import models
from django.utils.text import slugify

class Sport(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, blank=True)  
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
    point_value = models.PositiveIntegerField(default=0)
    is_negative = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.sport})"


class Position(models.Model):
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    abbreviation = models.CharField(max_length=3, blank=True)

    def __str__(self):
        return f"{self.name} ({self.sport})"
