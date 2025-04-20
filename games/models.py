from django.db import models
from sports.models import Sport, SportStatType, Position
from django.db.models import Sum
from rest_framework.exceptions import ValidationError
from django.utils import timezone
from leagues.models import League, Season


class Game(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        POSTPONED = "postponed", "Postponed"

    class Type(models.TextChoices):
        LEAGUE = "league", "League"
        TOURNAMENT = "tournament", "Tournament"
        NORMAL = "normal", "Normal"

    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    league = models.ForeignKey(League, on_delete=models.CASCADE, null=True)
    season = models.ForeignKey(Season, on_delete=models.CASCADE, null=True, related_name="games")
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.NORMAL)
    is_recorded = models.BooleanField(default=False)
    creator = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="creator")

    home_team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="home_games")
    away_team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="away_games")
    home_team_score = models.PositiveIntegerField(default=0)
    away_team_score = models.PositiveIntegerField(default=0)

    date = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED, blank=True)

    current_period = models.PositiveIntegerField(default=1)
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
        ordering = ["date"]

    def __str__(self):
        return f"{self.date.strftime('%Y-%m-%d')}: {self.home_team} vs {self.away_team}"

    def clean(self):
        errors = {}
        if self.home_team == self.away_team:
            errors["teams"] = "Home and away teams cannot be the same"
        if self.home_team.sport != self.sport or self.away_team.sport != self.sport:
            errors["sport"] = "Teams must belong to the game's sport"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.type == self.Type.NORMAL:
            self.is_recorded = False
        super().save(*args, **kwargs)

    def update_scores(self):
        scores = self._calculate_team_scores()
        Game.objects.filter(pk=self.pk).update(**scores)
        self.refresh_from_db()

    def _calculate_team_scores(self):
        from django.db.models import Sum

        def score(team):
            return PlayerStat.objects.filter(
                game=self,
                player__team=team,
                stat_type__point_value__gt=0
            ).aggregate(total=Sum("stat_type__point_value"))["total"] or 0

        return {
            "home_team_score": score(self.home_team),
            "away_team_score": score(self.away_team)
        }

    def start_game(self):
        if self.status != self.Status.SCHEDULED:
            raise ValidationError("Game can only start from scheduled status")
        if not self.date:
            raise ValidationError({"error": "Please specify a start date before launching the game."})

        self.validate_starting_lineup()
        self.status = self.Status.IN_PROGRESS
        self.started_at = timezone.now()
        self.save()

    def complete_game(self):
        if self.status != self.Status.IN_PROGRESS:
            raise ValueError(f"Cannot complete game in {self.status} status")

        self.status = self.Status.COMPLETED
        self.ended_at = timezone.now()
        self.duration = self.ended_at - self.started_at if self.started_at else None
        self.save(update_fields=["status", "ended_at", "duration", "updated_at"])

    def next_period(self):
        if self.status != self.Status.IN_PROGRESS:
            raise ValueError(f"Cannot proceed to next period in {self.status} status")
        self.current_period += 1
        self.save(update_fields=["current_period"])

    def validate_starting_lineup(self):
        sport = self.sport
        errors = []

        for team, label in [(self.home_team, "Home"), (self.away_team, "Away")]:
            count = self.starting_lineup.filter(team=team).count()
            if count != sport.max_players_on_field:
                errors.append(f"{label} team needs exactly {sport.max_players_on_field} starters")

        if errors:
            raise ValidationError(" ".join(errors))

    def get_lineup_status(self):
        return {
            "home_ready": self._is_team_ready(self.home_team),
            "away_ready": self._is_team_ready(self.away_team)
        }

    def _is_team_ready(self, team):
        return self.starting_lineup.filter(team=team).count() == self.sport.max_players_on_field

    def get_current_players(self, team):
        starters = self.starting_lineup.filter(team=team, is_starting=True).select_related('player')
        current = {s.player_id: s for s in starters}

        substitutions = self.substitutions.filter(
            substitute_in__team=team, period__lte=self.current_period
        ).order_by("timestamp")

        for sub in substitutions:
            if sub.substitute_out_id in current:
                current[sub.substitute_in_id] = StartingLineup(
                    player=sub.substitute_in,
                    team=team,
                    game=self,
                    is_starting=False
                )
                del current[sub.substitute_out_id]

        return list(current.values())

    @property
    def winner(self):
        if self.status != self.Status.COMPLETED:
            return None  # Match is still in progress

        if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
            home_sets = self.sets.filter(winner=self.home_team).count()
            away_sets = self.sets.filter(winner=self.away_team).count()

            # If a team has reached the win threshold
            if home_sets >= self.sport.win_threshold:
                return self.home_team
            elif away_sets >= self.sport.win_threshold:
                return self.away_team

            # If no tie is allowed and neither team has reached the win threshold
            if not self.sport.has_tie:
                return None  # No winner yet, match is ongoing (no tie allowed)

            # If tie is allowed
            return None  # Tie, no winner

        else:
            # Points-based scoring logic
            if self.home_team_score > self.away_team_score:
                return self.home_team
            elif self.away_team_score > self.home_team_score:
                return self.away_team
            return None  # Tie

    @property
    def score_summary(self):
        if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
            return {
                "sets": [
                    {"period": s.period, "home": s.home_team_score, "away": s.away_team_score}
                    for s in self.sets.all()
                ],
                "home_sets_won": self.sets.filter(winner=self.home_team).count(),
                "away_sets_won": self.sets.filter(winner=self.away_team).count(),
            }
        return {
            "home": self.home_team_score,
            "away": self.away_team_score,
            "difference": abs(self.home_team_score - self.away_team_score),
        }

# For Set Type Sports
class GameSet(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="sets")
    period = models.PositiveIntegerField()
    home_team_score = models.PositiveIntegerField(default=0)
    away_team_score = models.PositiveIntegerField(default=0)
    winner = models.ForeignKey("teams.Team", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        unique_together = ("game", "period")
        ordering = ["period"]
    
    def save(self, *args, **kwargs):
        self.determine_winner()
        super().save(*args, **kwargs)
    
    def determine_winner(self):
        sport = self.game.sport
        point_threshold = getattr(sport, "set_point_threshold", 25)  
        point_cap = getattr(sport, "set_point_cap", None)
        margin = getattr(sport, "win_by_margin", 2)

        # Win by margin logic
        if self.home_team_score >= point_threshold and (self.home_team_score - self.away_team_score) >= margin:
            self.winner = self.game.home_team
        elif self.away_team_score >= point_threshold and (self.away_team_score - self.home_team_score) >= margin:
            self.winner = self.game.away_team
        # Cap override — force win at cap
        elif point_cap:
            if self.home_team_score == point_cap:
                self.winner = self.game.home_team
            elif self.away_team_score == point_cap:
                self.winner = self.game.away_team
            else:
                self.winner = None
        else:
            self.winner = None

class PlayerStat(models.Model):
    player = models.ForeignKey(
        "teams.Player", on_delete=models.CASCADE, related_name="player_stats"
    )
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
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="substitutions")
    substitute_in = models.ForeignKey("teams.Player", on_delete=models.CASCADE, related_name="substitutions_in")
    substitute_out = models.ForeignKey("teams.Player", on_delete=models.CASCADE, related_name="substitutions_out")
    period = models.PositiveIntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["game", "period"]),
            models.Index(fields=["substitute_in", "substitute_out"]),
        ]

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
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="starting_lineup")
    player = models.ForeignKey("teams.Player", on_delete=models.CASCADE)
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE)
    is_starting = models.BooleanField(default=True)

    class Meta:
        unique_together = ("game", "player")  # A player can't start multiple times

    def __str__(self):
        return f"{self.player} ({self.team}) - {'Starter' if self.is_starting else 'Bench'}"
