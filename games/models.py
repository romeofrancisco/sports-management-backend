from django.db import models
from sports.models import Sport, SportStatType, Position
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
                stat_type__point_value__gt=0,
            ).aggregate(total=Sum("stat_type__point_value"))["total"]
            or 0
        )

        # Single query for away team
        away_score = (
            PlayerStat.objects.filter(
                game=self,
                player__team=self.away_team,
                stat_type__point_value__gt=0,
            ).aggregate(total=Sum("stat_type__point_value"))["total"]
            or 0
        )

        # Atomic update
        Game.objects.filter(pk=self.pk).update(
            home_team_score=home_score, away_team_score=away_score
        )
        self.refresh_from_db()

    def start_game(self):
        """Start game with validation of existing lineup"""
        if self.status != self.Status.SCHEDULED:
            raise ValidationError("Game can only start from scheduled status")
        
        self.validate_starting_lineup()
        
        self.status = self.Status.IN_PROGRESS
        self.started_at = timezone.now()
        self.save()

    def validate_starting_lineup(self):
        """Validate lineup requirements"""
        sport = self.sport
        home_count = self.starting_lineup.filter(team=self.home_team).count()
        away_count = self.starting_lineup.filter(team=self.away_team).count()

        errors = []
        if home_count != sport.max_players_on_field:
            errors.append(
                f"Home team needs exactly {sport.max_players_on_field} starters"
            )
        if away_count != sport.max_players_on_field:
            errors.append(
                f"Away team needs exactly {sport.max_players_on_field} starters"
            )
        
        if errors:
            raise ValidationError(" ".join(errors))

    def validate_starting_lineup(self):
        sport = self.sport
        home_starters = self.starting_lineup.filter(team=self.home_team).count()
        away_starters = self.starting_lineup.filter(team=self.away_team).count()

        errors = []
        if home_starters != sport.max_players_on_field:
            errors.append(
                f"Home team needs exactly {sport.max_players_on_field} starters"
            )
        if away_starters != sport.max_players_on_field:
            errors.append(
                f"Away team needs exactly {sport.max_players_on_field} starters"
            )

        if errors:
            raise ValidationError(" ".join(errors))

    def complete_game(self):
        if self.status != self.Status.IN_PROGRESS:
            raise ValueError(f"Cannot complete game in {self.status} status")

        self.status = self.Status.COMPLETED
        self.ended_at = timezone.now()

        if self.started_at:
            self.duration = self.ended_at - self.started_at

        self.save(update_fields=["status", "ended_at", "duration", "updated_at"])

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
    period = models.PositiveIntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["game", "player"]),
            models.Index(fields=["stat_type"]),
        ]
        ordering = ["-timestamp"]

    def clean(self):
        if self.game.status != Game.Status.IN_PROGRESS:
            raise ValidationError("Stats can only be recorded for in-progress games")
        if self.period > self.game.current_period:
            raise ValidationError("Cannot record stats for future periods")
        if self.player.team not in [self.game.home_team, self.game.away_team]:
            raise ValidationError("Player is not part of this game")
        if self.stat_type.sport != self.game.sport:
            raise ValidationError("Stat type doesn't match game sport")


class Substitution(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    substitute_in = models.ForeignKey(
        "teams.Player", on_delete=models.CASCADE, related_name="substitutions_in"
    )
    substitute_out = models.ForeignKey(
        "teams.Player", on_delete=models.CASCADE, related_name="substitutions_out"
    )
    period = models.PositiveIntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("game", "substitute_out", "period")
        ordering = ["-timestamp"]

    def clean(self):
        # Validate same team
        if self.substitute_in.team != self.substitute_out.team:
            raise ValidationError("Players must be from the same team")

        # Validate game participation
        game_teams = [self.game.home_team, self.game.away_team]
        if self.substitute_in.team not in game_teams:
            raise ValidationError("Substitute in player not in this game")

    def __str__(self):
        return f"{self.substitute_out} ↔ {self.substitute_in} (Period {self.period})"


class StartingLineup(models.Model):
    game = models.ForeignKey(
        Game, on_delete=models.CASCADE, related_name="starting_lineup"
    )
    player = models.ForeignKey("teams.Player", on_delete=models.CASCADE)
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE)
    is_starting = models.BooleanField(default=True)
    position = models.ForeignKey(Position, on_delete=models.SET_NULL, null=True)
    is_starting = models.BooleanField(default=True, editable=False)

    class Meta:
        unique_together = ("game", "player")  # A player can't start multiple times

    def __str__(self):
        return f"{self.player} ({self.team}) - {'Starter' if self.is_starting else 'Bench'}"
