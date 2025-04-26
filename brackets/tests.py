from django.test import TestCase, override_settings
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from leagues.models import League, Season
from sports.models import Sport, SportStatType
from teams.models import Team
from brackets.models import Bracket, BracketRound, BracketMatch
from games.models import Game
from django.contrib.auth import get_user_model

User = get_user_model()


class BracketFlowTestCase(TestCase):
    def setUp(self):
        """
        Set up the basic objects required for your tests:
          - Create a sport and league.
          - Create a season associated to the league.
          - Create multiple teams belonging to that sport.
          - Create a Bracket for the season.
          - Create a first round with two matches.
        """
        # Create a basic sport. (Make sure your Sport model has required fields, adjust as needed.)
        self.sport = Sport.objects.create(name="Basketball", scoring_type="points", max_players_on_field=5)
        
        # Create a League object. For the season, you might need to set start and end dates; adjust these as required.
        self.league = League.objects.create(name="Test League", sport=self.sport)
        
        # Create Season (adjust start/end dates if needed)
        self.season = Season.objects.create(
            league=self.league,
            year=2025,
            name="Spring",
            status=Season.Status.ONGOING,
            start_date=timezone.now().date(),
            end_date=timezone.now().date()
        )
        
        # Create teams and assign them to the league. We need at least four teams (for two matches).
        self.team1 = Team.objects.create(name="Team A", sport=self.sport)
        self.team2 = Team.objects.create(name="Team B", sport=self.sport)
        self.team3 = Team.objects.create(name="Team C", sport=self.sport)
        self.team4 = Team.objects.create(name="Team D", sport=self.sport)
        
        # Add teams to the league (through the many-to-many field)
        self.season.teams.add(self.team1, self.team2, self.team3, self.team4)
        
        # Create a Bracket for this season. You may add additional fields as needed.
        self.bracket = Bracket.objects.create(
            season=self.season,
            elimination_type=Bracket.ELIMINATION_TYPES.ROUND_ROBIN,
            current_round=1
        )
        
        # Create the first round in the bracket.
        self.round1 = BracketRound.objects.create(bracket=self.bracket, round_number=1)
        
        # Create two matches in round 1.
        # The first match: Team A vs Team B
        self.match1 = BracketMatch.objects.create(
            bracket=self.bracket,
            round=self.round1,
            home_team=self.team1,
            away_team=self.team2
        )
        # The second match: Team C vs Team D
        self.match2 = BracketMatch.objects.create(
            bracket=self.bracket,
            round=self.round1,
            home_team=self.team3,
            away_team=self.team4
        )
    
    def simulate_game_completion(self, match, winner):
        """
        Create and complete a Game that is linked to the given bracket match.
        This will trigger the signal to update the match winner and attempt to advance the bracket.
        """
        # Create a Game for the match.
        game = Game.objects.create(
            sport=self.sport,
            league=self.league,
            season=self.season,
            home_team=match.home_team,
            away_team=match.away_team,
            status=Game.Status.SCHEDULED,  # Initially scheduled
            date=timezone.now()
        )
        
        # Link game to the match
        match.game = game
        match.save(update_fields=["game"])
        
        
        game = match.game
        if winner == game.home_team:
            game.home_team_score = 25
            game.away_team_score = 15
        else:
            game.home_team_score = 15
            game.away_team_score = 25
        game.save()
        
        # Now simulate the game being completed.
        # (Make sure your game.complete_game() method sets the status properly.)
        game.status = Game.Status.COMPLETED
        game.ended_at = timezone.now()
        game.save(update_fields=["status", "ended_at"])
        
        # To simulate the signal behavior, you might need to explicitly call a method
        # if you are not relying entirely on the auto-post-save signals.
        # In our design, the post_save on the Game model will update match.winner.
        
        print("Game winner:", game.winner)
        print("Next match:", match.next_match)
        
        # Refetch the match to ensure it is updated.
        match.refresh_from_db()
        return game
    
    def test_bracket_round_advancement(self):
        """
        Simulates both first round games being completed,
        then tests that:
          - The bracket's current_round is updated to the next round.
          - A new round (Round 2) is created.
          - Both match1 and match2 have their `next_match` field set to the new match.
          - The new next_match receives both winners as home_team/away_team as assigned by signals.
        """
        # Simulate game completion for the first match; assume Team A wins.
        self.simulate_game_completion(self.match1, self.team1)
        # Simulate game completion for the second match; assume Team C wins.
        self.simulate_game_completion(self.match2, self.team3)
        
        # After both matches complete, signals should trigger round advancement.
        # Refresh the bracket instance.
        
        self.bracket.refresh_from_db()
        self.assertEqual(self.bracket.current_round, 2)
        
        # Check that a Round 2 was created.
        next_round = BracketRound.objects.get(bracket=self.bracket, round_number=2)
        # In our implementation, there should be one match in round 2.
        next_round_matches = next_round.matches.all()
        self.assertEqual(next_round_matches.count(), 1)
        
        next_match = next_round_matches.first()
        # Verify that both match1 and match2 have been linked to the new match.
        self.match1.refresh_from_db()
        self.match2.refresh_from_db()
        self.assertEqual(self.match1.next_match, next_match)
        self.assertEqual(self.match2.next_match, next_match)
        
        # Check that the winners advanced into the next match.
        # Depending on your signal logic, one winner becomes home_team, the other away_team.
        self.assertIn(self.team1, [next_match.home_team, next_match.away_team])
        self.assertIn(self.team3, [next_match.home_team, next_match.away_team])
    
    def test_no_duplicate_round_creation(self):
        """
        Tests that if the signals are triggered again (e.g. by a double save),
        no duplicate next round or match is created.
        """
        # Complete both matches.
        self.simulate_game_completion(self.match1, self.team1)
        self.simulate_game_completion(self.match2, self.team3)
        
        # Now, trigger the signal a second time (simulate a redundant save).
        self.match1.save()
        self.match2.save()
        
        # There should still be only one next round.
        rounds = self.bracket.rounds.filter(round_number=2)
        self.assertEqual(rounds.count(), 1)
        
        # Also ensure that next_match is still the same.
        next_round = rounds.first()
        next_matches = list(next_round.matches.all())
        self.assertEqual(len(next_matches), 1)
    
    def test_incomplete_round_does_not_advance(self):
        """
        Tests that if one of the matches in the current round is not completed,
        the next round is not created.
        """
        # Complete only the first match.
        self.simulate_game_completion(self.match1, self.team1)
        # Do NOT complete the second match.
        self.match2.refresh_from_db()
        
        # Since not all matches have winners, current_round should remain 1.
        self.bracket.refresh_from_db()
        self.assertEqual(self.bracket.current_round, 1)
        # There should be no round 2.
        self.assertFalse(self.bracket.rounds.filter(round_number=2).exists())

    def test_final_round_has_no_next_match(self):
        # Complete Round 1
        self.simulate_game_completion(self.match1, self.team1)
        self.simulate_game_completion(self.match2, self.team3)

        # Now, get the final match (round 2)
        final_round = BracketRound.objects.get(bracket=self.bracket, round_number=2)
        final_match = final_round.matches.first()

        # Complete it
        self.simulate_game_completion(final_match, self.team1)

        final_match.refresh_from_db()
        self.assertIsNone(final_match.next_match)

        # Ensure no further rounds were created
        self.assertFalse(self.bracket.rounds.filter(round_number=3).exists())
        
    def test_match_winner_is_set_after_game_completion(self):
        self.simulate_game_completion(self.match1, self.team1)
        self.match1.refresh_from_db()
        self.assertEqual(self.match1.winner, self.team1)
