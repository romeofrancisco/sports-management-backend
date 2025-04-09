from django.db import models
from django.core.exceptions import ValidationError
from django.db.models import Sum, F, Q

class League(models.Model):
    name = models.CharField(max_length=255)
    sport = models.ForeignKey("sports.Sport", on_delete=models.CASCADE)
    teams = models.ManyToManyField("teams.Team", related_name="leagues")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ["name", "sport"]

    def __str__(self):
        return f"{self.name} ({self.sport})"

    def clean(self):
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
    
    @property
    def has_bracket(self):
        """Check if any bracket exists for this season"""
        return self.brackets.exists()

    def standings(self):
        sport = self.league.sport
        scoring_type = sport.scoring_type  # "points", "sets", or "goals"
        games = self.games.filter(status="completed", season=self.id)
        standings = []

        for team in self.league.teams.all():
            team_games = games.filter(Q(home_team=team) | Q(away_team=team))
            matches_played = team_games.count()

            wins = team_games.filter(
                Q(home_team=team, home_team_score__gt=F("away_team_score")) |
                Q(away_team=team, away_team_score__gt=F("home_team_score"))
            ).count()

            losses = team_games.filter(
                Q(home_team=team, home_team_score__lt=F("away_team_score")) |
                Q(away_team=team, away_team_score__lt=F("home_team_score"))
            ).count()

            ties = 0
            if sport.has_tie:
                ties = team_games.filter(
                    Q(home_team=team, home_team_score=F("away_team_score")) |
                    Q(away_team=team, away_team_score=F("home_team_score"))
                ).count()

            # Scoring values
            home = games.filter(home_team=team).aggregate(
                scored=Sum('home_team_score'),
                conceded=Sum('away_team_score')
            )
            away = games.filter(away_team=team).aggregate(
                scored=Sum('away_team_score'),
                conceded=Sum('home_team_score')
            )
            scored = (home['scored'] or 0) + (away['scored'] or 0)
            conceded = (home['conceded'] or 0) + (away['conceded'] or 0)
            goal_difference = scored - conceded

            team_data = {
                "team_id": team.id,
                "team_name": team.name,
                "matches_played": matches_played,
                "wins": wins,
                "losses": losses,
            }

            if sport.has_tie:
                team_data["ties"] = ties

            if scoring_type == "points":
                points = wins * 3
                win_percentage = round(wins / matches_played, 3) if matches_played else 0
                team_data.update({
                    "points": points,
                    "win_percentage": win_percentage,
                })

            elif scoring_type == "sets":
                set_ratio = round(scored / conceded, 2) if conceded else scored
                team_data.update({
                    "sets_won": scored,
                    "sets_lost": conceded,
                    "set_ratio": set_ratio,
                })

            elif scoring_type == "goals":
                point_ratio = round(scored / conceded, 2) if conceded else scored
                team_data.update({
                    "points_won": scored,
                    "points_lost": conceded,
                    "point_ratio": point_ratio,
                    "goal_difference": goal_difference,
                })

            standings.append(team_data)

        # Custom sorting based on scoring type
        def sort_key(team):
            if scoring_type == "points":
                return (-team["points"], -team.get("win_percentage", 0))
            elif scoring_type == "sets":
                return (-team.get("set_ratio", 0), -team.get("sets_won", 0))
            elif scoring_type == "goals":
                return (-team.get("point_ratio", 0), -team.get("goal_difference", 0))
            return (-team.get("wins", 0),)

        sorted_standings = sorted(standings, key=sort_key)

        # Add rankings to the standings
        for rank, team in enumerate(sorted_standings, start=1):
            team["rank"] = rank
            
        return sorted_standings