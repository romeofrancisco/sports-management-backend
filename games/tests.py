from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import Game, GameSet, PlayerStat
from sports.models import Sport, SportStatType
from teams.models import Team, Player
from users.models import User

class SetBasedSportsGameTests(TestCase):
    """Tests for set-based sports game logic (volleyball, tennis, etc.)"""
    
    def setUp(self):
        """Set up test data with sport, teams, and players"""
        # Create sport (volleyball)
        self.sport = Sport.objects.create(
            name="Volleyball",
            scoring_type=Sport.SCORING_TYPES.SETS,
            max_period=5,
            win_threshold=3,         # Best of 5 - need 3 sets to win
            win_points_threshold=25,  # Need 25 points to win a set
            win_margin=2,            # Need 2 point margin to win a set
            has_period=True,
            max_players_on_field=6,
            max_players_per_team=12
        )
        
        # Create teams
        self.home_team = Team.objects.create(
            name="Home Team",
            abbreviation="HOME",
            sport=self.sport
        )
        self.away_team = Team.objects.create(
            name="Away Team",
            abbreviation="AWAY",
            sport=self.sport
        )
        
        # Create players for both teams
        self.home_players = []
        self.away_players = []
        for i in range(6):
            # Create home team player
            home_user = User.objects.create(
                email=f"home{i}@test.com",
                password="password",
                first_name=f"Home{i}",
                last_name="Player"
            )
            home_player = Player.objects.create(
                user=home_user,
                team=self.home_team,
                jersey_number=i+1
            )
            self.home_players.append(home_player)
            
            # Create away team player
            away_user = User.objects.create(
                email=f"away{i}@test.com",
                password="password",
                first_name=f"Away{i}",
                last_name="Player"
            )
            away_player = Player.objects.create(
                user=away_user,
                team=self.away_team,
                jersey_number=i+1
            )
            self.away_players.append(away_player)
        
        # Create a point scoring stat type
        self.point_stat = SportStatType.objects.create(
            name="Point",
            code="PTS",
            sport=self.sport,
            point_value=1,
            is_record=True,
            is_counter=True
        )
        
        # Create game
        self.game = Game.objects.create(
            sport=self.sport,
            home_team=self.home_team,
            away_team=self.away_team,
            date=timezone.now(),
            location="Test Court",
            status=Game.Status.SCHEDULED
        )
        
        # Add starting lineup for both teams
        for player in self.home_players:
            self.game.starting_lineup.create(team=self.home_team, player=player, is_starting=True)
        for player in self.away_players:
            self.game.starting_lineup.create(team=self.away_team, player=player, is_starting=True)
        
        # Start the game
        self.game.start_game()
        
    def test_win_points_threshold_validation(self):
        """Test that validation error is raised if recording points beyond win threshold"""
        # Score 24 points for home team 
        for i in range(24):
            PlayerStat.objects.create(
                game=self.game,
                player=self.home_players[0], 
                stat_type=self.point_stat,
                period=self.game.current_period
            )
        
        # Score 22 points for away team 
        for i in range(22):
            PlayerStat.objects.create(
                game=self.game,
                player=self.away_players[0], 
                stat_type=self.point_stat,
                period=self.game.current_period
            )
            
        # Update scores
        self.game.update_scores()
        self.game.refresh_from_db()
        
        # Verify current score
        self.assertEqual(self.game.home_team_score, 24)
        self.assertEqual(self.game.away_team_score, 22)
        
        # Recording one more point should succeed as it reaches the win threshold with margin
        PlayerStat.objects.create(
            game=self.game,
            player=self.home_players[0], 
            stat_type=self.point_stat,
            period=self.game.current_period
        )
        
        # Update scores
        self.game.update_scores()
        self.game.refresh_from_db()
        
        # Verify current score
        self.assertEqual(self.game.home_team_score, 25)
        self.assertEqual(self.game.away_team_score, 22)
        
        # Recording one more point should fail as home team has already won this set
        with self.assertRaises(ValidationError) as context:
            PlayerStat.objects.create(
                game=self.game,
                player=self.home_players[0], 
                stat_type=self.point_stat,
                period=self.game.current_period
            )
        
        # Verify that the error message mentions advancing to the next set
        self.assertIn("advance to next", str(context.exception))
        
    def test_next_period_after_win_threshold(self):
        """Test that next_period works after winning a set at threshold"""
        # Score 25 points for home team
        for i in range(25):
            PlayerStat.objects.create(
                game=self.game,
                player=self.home_players[0], 
                stat_type=self.point_stat,
                period=self.game.current_period
            )
        
        # Score 20 points for away team
        for i in range(20):
            PlayerStat.objects.create(
                game=self.game,
                player=self.away_players[0], 
                stat_type=self.point_stat,
                period=self.game.current_period
            )
            
        # Update scores
        self.game.update_scores()
        self.game.refresh_from_db()
        
        # Verify set score
        self.assertEqual(self.game.home_team_score, 25)
        self.assertEqual(self.game.away_team_score, 20)
        
        # Move to next set
        self.game.next_period()
        self.game.refresh_from_db()
        
        # Verify period and score
        self.assertEqual(self.game.current_period, 2)
        self.assertEqual(self.game.home_team_score, 0)
        self.assertEqual(self.game.away_team_score, 0)
        
        # Check that set 1 was properly recorded
        set1 = GameSet.objects.get(game=self.game, period=1)
        self.assertEqual(set1.home_team_score, 25)
        self.assertEqual(set1.away_team_score, 20)
        self.assertEqual(set1.winner, self.home_team)
    
    def test_complete_game_with_insufficient_sets(self):
        """Test that game cannot be completed without meeting the win threshold for sets"""
        # Win first set for home team
        for i in range(25):
            PlayerStat.objects.create(
                game=self.game,
                player=self.home_players[0], 
                stat_type=self.point_stat,
                period=self.game.current_period
            )
        self.game.update_scores()
        self.game.next_period()
            
        # Win second set for away team
        for i in range(25):
            PlayerStat.objects.create(
                game=self.game,
                player=self.away_players[0], 
                stat_type=self.point_stat,
                period=self.game.current_period
            )
        self.game.update_scores()
        self.game.next_period()
            
        # Cannot complete game yet since neither team has won 3 sets
        with self.assertRaises(ValidationError) as context:
            self.game.complete_game()
            
        self.assertIn(f"Neither team has won {self.sport.win_threshold} sets", str(context.exception))
        
    def test_auto_complete_game_at_win_threshold(self):
        """Test that game automatically completes when a team reaches the win threshold for sets"""
        # Win 3 sets for home team
        for set_num in range(3):
            # Score 25 points for home team in current set
            for i in range(25):
                PlayerStat.objects.create(
                    game=self.game,
                    player=self.home_players[0], 
                    stat_type=self.point_stat,
                    period=self.game.current_period
                )
            # Score 15 points for away team in current set
            for i in range(15):
                PlayerStat.objects.create(
                    game=self.game,
                    player=self.away_players[0], 
                    stat_type=self.point_stat,
                    period=self.game.current_period
                )
                
            self.game.update_scores()
            
            if set_num < 2:  # Only advance if not the last set
                self.game.next_period()
                
        # When we call next_period after the third set win, the game should auto-complete
        self.game.next_period()
        self.game.refresh_from_db()
        
        # Verify the game is completed
        self.assertEqual(self.game.status, Game.Status.COMPLETED)
        self.assertIsNotNone(self.game.ended_at)
        self.assertEqual(self.game.winner, self.home_team)
        
    def test_edge_case_win_with_extended_score(self):
        """Test set win with extended score (beyond threshold but with required margin)"""
        # Score 24 points for home team
        for i in range(24):
            PlayerStat.objects.create(
                game=self.game,
                player=self.home_players[0], 
                stat_type=self.point_stat,
                period=self.game.current_period
            )
        
        # Score 24 points for away team
        for i in range(24):
            PlayerStat.objects.create(
                game=self.game,
                player=self.away_players[0], 
                stat_type=self.point_stat,
                period=self.game.current_period
            )
            
        self.game.update_scores()
        self.game.refresh_from_db()
        
        # At 24-24, we need a 2-point margin, so both teams can continue scoring
        
        # Score 1 more for home (25-24)
        PlayerStat.objects.create(
            game=self.game,
            player=self.home_players[0], 
            stat_type=self.point_stat,
            period=self.game.current_period
        )
        self.game.update_scores()
        
        # Score 1 more for away (25-25)
        PlayerStat.objects.create(
            game=self.game,
            player=self.away_players[0], 
            stat_type=self.point_stat,
            period=self.game.current_period
        )
        self.game.update_scores()
        
        # Score 1 more for home (26-25)
        PlayerStat.objects.create(
            game=self.game,
            player=self.home_players[0], 
            stat_type=self.point_stat,
            period=self.game.current_period
        )
        self.game.update_scores()
        
        # Score 1 more for away (26-26)
        PlayerStat.objects.create(
            game=self.game,
            player=self.away_players[0], 
            stat_type=self.point_stat,
            period=self.game.current_period
        )
        self.game.update_scores()
        
        # Score 2 more for home (28-26) - should win the set with 2-point margin
        PlayerStat.objects.create(
            game=self.game,
            player=self.home_players[0], 
            stat_type=self.point_stat,
            period=self.game.current_period
        )
        PlayerStat.objects.create(
            game=self.game,
            player=self.home_players[0], 
            stat_type=self.point_stat,
            period=self.game.current_period
        )
        self.game.update_scores()
        self.game.refresh_from_db()
        
        # Attempting to score more points should fail as set is over
        with self.assertRaises(ValidationError) as context:
            PlayerStat.objects.create(
                game=self.game,
                player=self.home_players[0], 
                stat_type=self.point_stat,
                period=self.game.current_period
            )
            
        self.assertIn("advance to next", str(context.exception))
        
        # Next period should work correctly
        self.game.next_period()
        self.game.refresh_from_db()
        self.assertEqual(self.game.current_period, 2)
        self.assertEqual(self.game.home_team_score, 0)
        self.assertEqual(self.game.away_team_score, 0)
