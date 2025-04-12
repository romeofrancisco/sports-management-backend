from django.db import models


class Bracket(models.Model):
    class ELIMINATION_TYPES(models.TextChoices):
        SINGLE = "single", "Single Elimination"
        DOUBLE = "double", "Double Elimination"
        ROUND_ROBIN = "round_robin", "Round Robin"

    season = models.ForeignKey("leagues.Season", on_delete=models.CASCADE, related_name="brackets")
    elimination_type = models.CharField(max_length=20, choices=ELIMINATION_TYPES)
    current_round = models.PositiveIntegerField(default=1)  # Track progress
    is_complete = models.BooleanField(default=False)
    winner = models.ForeignKey("teams.Team", null=True,on_delete=models.SET_NULL, related_name="bracket_winner")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.sport} - {self.season} ({self.elimination_type})"

class BracketRound(models.Model):
    bracket = models.ForeignKey(Bracket, on_delete=models.CASCADE, related_name="rounds")
    round_number = models.PositiveIntegerField()
    is_complete = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Round {self.round_number} of {self.bracket}"


class BracketMatch(models.Model):
    bracket = models.ForeignKey(Bracket, on_delete=models.CASCADE)
    round = models.ForeignKey(BracketRound, on_delete=models.CASCADE, related_name="matches")
    home_team = models.ForeignKey("teams.Team", null=True, blank=True, on_delete=models.SET_NULL, related_name="home_matches")
    away_team = models.ForeignKey("teams.Team", null=True, blank=True, on_delete=models.SET_NULL, related_name="away_matches")
    winner = models.ForeignKey("teams.Team", null=True, blank=True, on_delete=models.SET_NULL, related_name="match_wins")
    next_match = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='previous_matches')
    game = models.OneToOneField("games.Game", null=True, blank=True, on_delete=models.SET_NULL, related_name="bracket_match")

    def __str__(self):
        return f"{self.home_team} vs {self.away_team} (Round {self.round.round_number})"
