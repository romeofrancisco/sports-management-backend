from django.db import models
from sports.models import Sport, SportStatType
from django.db.models import Q


class Game(models.Model):
    STATUS_CHOICES = (
        ("scheduled", "Scheduled"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("postponed", "Postponed"),
        ("canceled", "Canceled"),
    )

    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    home_team_score = models.PositiveIntegerField(default=0)
    away_team_score = models.PositiveIntegerField(default=0)
    home_team = models.ForeignKey(
        'teams.Team', on_delete=models.CASCADE, related_name="home_team"
    )
    away_team = models.ForeignKey(
        'teams.Team', on_delete=models.CASCADE, related_name="away_team"
    )
    date = models.DateTimeField()
    location = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="scheduled"
    )
    current_period = models.PositiveIntegerField(
        default=1
    )  # For tracking quarters/sets
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.date} - {self.sport} Game"

    def update_scores(self):
        # Calculate home score
        home_stats = PlayerStat.objects.filter(
            game=self,
            player__team=self.home_team,
            success=True,
            stat_type__point_value__gt=0
        )
        self.home_team_score = sum(stat.stat_type.point_value for stat in home_stats)

        # Calculate away score
        away_stats = PlayerStat.objects.filter(
            game=self,
            player__team=self.away_team,
            success=True,
            stat_type__point_value__gt=0
        )
        self.away_team_score = sum(stat.stat_type.point_value for stat in away_stats)

        self.save(update_fields=['home_team_score', 'away_team_score'])


class PlayerStat(models.Model):
    player = models.ForeignKey('teams.Player', on_delete=models.CASCADE)
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    stat_type = models.ForeignKey(SportStatType, on_delete=models.CASCADE)
    period = models.PositiveIntegerField()  # Quarter/Set number
    success = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.player} - {self.stat_type} ({'success' if self.success else 'fail'})"
