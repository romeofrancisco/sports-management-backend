from django.db import models
from django.core.exceptions import ValidationError


class Bracket(models.Model):
    class ELIMINATION_TYPES(models.TextChoices):
        SINGLE = "single", "Single Elimination"
        DOUBLE = "double", "Double Elimination"
        ROUND_ROBIN = "round_robin", "Round Robin"

    season = models.OneToOneField(
        "leagues.Season",
        on_delete=models.CASCADE,
        related_name="bracket",
        null=True,
        blank=True,
    )
    tournament = models.OneToOneField(
        "tournaments.Tournament",
        on_delete=models.CASCADE,
        related_name="bracket",
        null=True,
        blank=True,
    )
    elimination_type = models.CharField(max_length=20, choices=ELIMINATION_TYPES)
    current_round = models.PositiveIntegerField(default=1)  # Track progress
    is_complete = models.BooleanField(default=False)
    winner = models.ForeignKey(
        "teams.Team",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bracket_winner",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.season:
            return (
                f"{self.season.league.sport} - {self.season} ({self.elimination_type})"
            )
        elif self.tournament:
            return f"{self.tournament.sport} - {self.tournament.name} ({self.elimination_type})"
        return f"Bracket ({self.elimination_type})"

    def team_count(self):
        """Return the number of teams in the bracket."""
        if self.season:
            return self.season.teams.count()
        elif self.tournament:
            return self.tournament.teams.count()
        return 0

    def clean(self):
        """Validate bracket before saving."""
        if self.elimination_type in (
            self.ELIMINATION_TYPES.SINGLE,
            self.ELIMINATION_TYPES.DOUBLE,
        ):
            count = self.team_count() or 0

            if count < 2 or (count & (count - 1)) != 0:
                raise ValidationError(
                    {
                        "__all__": (
                            f"Single and double elimination brackets must include at least two teams, "
                            f"and the total number of teams must be a power of two (e.g., 2, 4, 8, 16...). "
                            f"Currently, there are {count} teams."
                        )
                    }
                )

    def save(self, *args, **kwargs):
        # Ensure validation runs before saving
        self.full_clean()
        super().save(*args, **kwargs)


class BracketRound(models.Model):
    bracket = models.ForeignKey(
        Bracket, on_delete=models.CASCADE, related_name="rounds"
    )
    round_number = models.PositiveIntegerField()
    is_complete = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Round {self.round_number} of {self.bracket}"


class BracketMatch(models.Model):
    bracket = models.ForeignKey(Bracket, on_delete=models.CASCADE)
    round = models.ForeignKey(
        BracketRound, on_delete=models.CASCADE, related_name="matches"
    )
    home_team = models.ForeignKey(
        "teams.Team",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="home_matches",
    )
    away_team = models.ForeignKey(
        "teams.Team",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="away_matches",
    )
    winner = models.ForeignKey(
        "teams.Team",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="match_wins",
    )
    next_match = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="previous_matches",
    )
    next_loser_match = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="previous_loser_matches",
    )
    game = models.OneToOneField(
        "games.Game",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="bracket_match",
    )
    is_filler = models.BooleanField(
        default=False
    )  # True if this is a placeholder match for visual balance

    def __str__(self):
        return f"{self.home_team} vs {self.away_team} (Round {self.round.round_number})"
