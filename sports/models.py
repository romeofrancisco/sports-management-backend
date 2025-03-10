from django.db import models

class Sport(models.Model):
    SCORING_STYLES = (
        ("points", "Points"),
        ("sets", "Sets"),
        ("goals", "Goals"),
    )
    
    name = models.CharField(max_length=100, unique=True)
    scoring_style = models.CharField(max_length=20, choices=SCORING_STYLES, default="points")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

        
class Position(models.Model):
    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    abbreviation = models.CharField(max_length=3, blank=True)
    
    def __str__(self):
        return f"{self.name} ({self.sport})"
        