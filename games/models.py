from django.db import models
from sports.models import Sport, SportStatType
from django.db.models import Sum
from django.core.exceptions import ValidationError
from django.utils import timezone


class Game(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        POSTPONED = "postponed", "Postponed"

    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    home_team_score = models.PositiveIntegerField(default=0)
    away_team_score = models.PositiveIntegerField(default=0)
    home_team = models.ForeignKey(
        "teams.Team", on_delete=models.CASCADE, related_name="home_games"
    )
    away_team = models.ForeignKey(
        "teams.Team", on_delete=models.CASCADE, related_name="away_games"
    )
    date = models.DateTimeField()
    location = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SCHEDULED
    )
    current_period = models.PositiveIntegerField(
        default=1
    )  # For tracking quarters/sets
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["status"]),
            models.Index(fields=["home_team", "away_team"]),
            models.Index(fields=["started_at"]),
            models.Index(fields=["ended_at"]),
        ]
        ordering = ["-date"]

    def clean(self):
        if self.home_team == self.away_team:
            raise ValidationError("Home and away teams cannot be the same")
        if self.home_team.sport != self.sport or self.away_team.sport != self.sport:
            raise ValidationError("Teams must belong to the game's sport")

    def __str__(self):
        return f"{self.date.strftime('%Y-%m-%d')}: {self.home_team} vs {self.away_team}"

    def update_scores(self):
        # Single query for home team
        home_score = (
            PlayerStat.objects.filter(
                game=self,
                player__team=self.home_team,
                success=True,
                stat_type__point_value__gt=0,
            ).aggregate(total=Sum("stat_type__point_value"))["total"]
            or 0
        )

        # Single query for away team
        away_score = (
            PlayerStat.objects.filter(
                game=self,
                player__team=self.away_team,
                success=True,
                stat_type__point_value__gt=0,
            ).aggregate(total=Sum("stat_type__point_value"))["total"]
            or 0
        )

        # Atomic update
        Game.objects.filter(pk=self.pk).update(
            home_team_score=home_score, away_team_score=away_score
        )
        self.refresh_from_db()

    def start_game(self, notes=""):
        if self.status != self.Status.SCHEDULED:
            raise ValueError(f"Cannot start game in {self.status} status")

        self.status = self.Status.IN_PROGRESS
        self.started_at = timezone.now()
        self.notes = notes or f"Game started at {timezone.now()}"
        self.save(update_fields=["status", "started_at", "notes"])

    def complete_game(self, notes=""):
        if self.status != self.Status.IN_PROGRESS:
            raise ValueError(f"Cannot complete game in {self.status} status")

        self.status = self.Status.COMPLETED
        self.ended_at = timezone.now()
        self.notes = notes or f"Game completed at {timezone.now()}"

        if self.started_at:
            self.duration = self.ended_at - self.started_at
            self.notes += f"\nDuration: {self.duration}"

        self.save(update_fields=["status", "ended_at", "duration", "notes", "updated_at"])

    @property
    def winner(self):
        if self.status != self.Status.COMPLETED:
            return None
        if self.home_team_score > self.away_team_score:
            return self.home_team
        elif self.away_team_score > self.home_team_score:
            return self.away_team
        return None  # Tie

    @property
    def score_summary(self):
        return {
            "home": self.home_team_score,
            "away": self.away_team_score,
            "difference": abs(self.home_team_score - self.away_team_score),
        }


class PlayerStat(models.Model):
    player = models.ForeignKey("teams.Player", on_delete=models.CASCADE)
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    stat_type = models.ForeignKey(SportStatType, on_delete=models.CASCADE)
    period = models.PositiveIntegerField()  # Quarter/Set number
    success = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.player} - {self.stat_type} ({'success' if self.success else 'fail'})"
