from django.db import models
from django.core.exceptions import ValidationError


class League(models.Model):
    class EliminationType(models.TextChoices):
        SINGLE = "single_elimination", "Single Elimination"
        DOUBLE = "double_elimination", "Double Elimination"

    name = models.CharField(max_length=255)
    sport = models.ForeignKey("sports.Sport", on_delete=models.CASCADE)
    teams = models.ManyToManyField("teams.Team", related_name="leagues")
    elimination_type = models.CharField(
        max_length=20,
        choices=EliminationType.choices,
        default=EliminationType.SINGLE,
        blank=False,
    )
    start_date = models.DateField()
    end_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]
        unique_together = ["name", "sport"]

    def __str__(self):
        return f"{self.name} ({self.sport})"

    @property
    def standings(self):
        standings = []
        for team in self.teams.all():
            # Access games through the league's game set
            games = self.games.filter(status="completed")

            # Calculate statistics
            wins = games.filter(
                models.Q(
                    home_team=team, home_team_score__gt=models.F("away_team_score")
                )
                | models.Q(
                    away_team=team, away_team_score__gt=models.F("home_team_score")
                )
            ).count()

            losses = games.filter(
                models.Q(
                    home_team=team, home_team_score__lt=models.F("away_team_score")
                )
                | models.Q(
                    away_team=team, away_team_score__lt=models.F("home_team_score")
                )
            ).count()

            ties = games.filter(
                models.Q(home_team=team, home_team_score=models.F("away_team_score"))
                | models.Q(away_team=team, away_team_score=models.F("home_team_score"))
            ).count()

            # Calculate points
            points_for = sum(
                [
                    sum(
                        games.filter(home_team=team).values_list(
                            "home_team_score", flat=True
                        )
                    ),
                    sum(
                        games.filter(away_team=team).values_list(
                            "away_team_score", flat=True
                        )
                    ),
                ]
            )

            points_against = sum(
                [
                    sum(
                        games.filter(home_team=team).values_list(
                            "away_team_score", flat=True
                        )
                    ),
                    sum(
                        games.filter(away_team=team).values_list(
                            "home_team_score", flat=True
                        )
                    ),
                ]
            )

            standings.append(
                {
                    "team_id": team.id,
                    "team_name": team.name,
                    "wins": wins,
                    "losses": losses,
                    "ties": ties,
                    "points_for": points_for,
                    "points_against": points_against,
                    "points_difference": points_for - points_against,
                }
            )

        return sorted(
            standings, key=lambda x: (-x["wins"], -x["ties"], -x["points_difference"])
        )

    def clean(self):
        # Validate league dates
        if self.start_date >= self.end_date:
            raise ValidationError("End date must be after start date")


class Season(models.Model):
    class Status(models.TextChoices):
        UPCOMING = "upcoming", "Upcoming"
        ONGOING = "ongoing", "Ongoing"
        COMPLETED = "completed", "Completed"
        CANCELED = "canceled", "Canceled"
        PAUSED = "paused", "Paused"
            
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="seasons")
    year = models.PositiveIntegerField()
    record_stats = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPCOMING)
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        ordering = ["-year"]
        unique_together = ["league", "year"]

    def __str__(self):
        return f"{self.league.name} Season {self.year}"

    def clean(self):
        if self.start_date >= self.end_date:
            raise ValidationError("Season end date must be after start date")
        if self.start_date < self.league.start_date:
            raise ValidationError("Season cannot start before league start date")
        if self.end_date > self.league.end_date:
            raise ValidationError("Season cannot end after league end date")
