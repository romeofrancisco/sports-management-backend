from django.db import models

class Bracket(models.Model):
    ELIMINATION_TYPES = [
        ('single', 'Single Elimination'),
        ('double', 'Double Elimination'),
    ]
    season = models.ForeignKey("leagues.Season", on_delete=models.CASCADE, related_name='brackets')
    elimination_type = models.CharField(max_length=10, choices=ELIMINATION_TYPES, default='single')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.sport} - {self.season} ({self.elimination_type})"
    
class BracketRound(models.Model):
    bracket = models.ForeignKey(Bracket, on_delete=models.CASCADE, related_name='rounds')
    round_number = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Round {self.round_number} of {self.bracket}"
    
class BracketMatch(models.Model):
    bracket = models.ForeignKey(Bracket, on_delete=models.CASCADE)
    round = models.ForeignKey(BracketRound, on_delete=models.CASCADE, related_name='matches')
    home_team = models.ForeignKey('teams.Team', related_name='home_matches', null=True, blank=True, on_delete=models.SET_NULL)
    away_team = models.ForeignKey('teams.Team', related_name='away_matches', null=True, blank=True, on_delete=models.SET_NULL)
    game = models.OneToOneField('games.Game', null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f"{self.home_team} vs {self.away_team} (Round {self.round.round_number})"    
