from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal

from .models import League, Season
from sports.models import Sport
from teams.models import Team
from games.models import Game
from brackets.models import Bracket

class LeagueModelTest(TestCase):
    """Test cases for the League model"""

    def setUp(self):
        """Set up test data for League model tests"""
        # Create a sport
        self.sport = Sport.objects.create(
            name="Basketball",
            scoring_type="points",
            max_players_per_team=12,
            max_players_on_field=5,
            has_period=True,
            max_period=4,
            has_tie=False,
            has_overtime=True
        )
        
        # Create a league
        self.league = League.objects.create(
            name="NBA",
            sport=self.sport
        )
        
        # Create some teams
        self.team1 = Team.objects.create(
            name="Lakers",
            abbreviation="LAL",
            sport=self.sport,
            division="male"
        )
        
        self.team2 = Team.objects.create(
            name="Celtics",
            abbreviation="BOS",
            sport=self.sport,
            division="male"
        )

        self.team3 = Team.objects.create(
            name="Warriors",
            abbreviation="GSW",
            sport=self.sport,
            division="male"
        )

    def test_league_creation(self):
        """Test that league objects are created correctly"""
        self.assertEqual(self.league.name, "NBA")
        self.assertEqual(self.league.sport, self.sport)
        self.assertIsNotNone(self.league.created_at)
        self.assertIsNotNone(self.league.updated_at)
        self.assertEqual(str(self.league), f"NBA (Basketball)")
        
    def test_league_unique_constraint(self):
        """Test that leagues with same name and sport cannot be created"""
        # Try creating another league with the same name and sport
        with self.assertRaises(Exception):
            League.objects.create(
                name="NBA",
                sport=self.sport
            )
    
    def test_league_standings_empty(self):
        """Test that league standings returns empty for a league with no seasons"""
        standings = self.league.standings()
        self.assertEqual(standings, [])

class SeasonModelTest(TestCase):
    """Test cases for the Season model"""
    
    def setUp(self):
        """Set up test data for Season model tests"""
        # Create a sport
        self.sport = Sport.objects.create(
            name="Basketball",
            scoring_type="points",
            max_players_per_team=12,
            max_players_on_field=5,
            has_period=True,
            max_period=4,
            has_tie=False,
            has_overtime=True
        )
        
        # Create a league
        self.league = League.objects.create(
            name="NBA",
            sport=self.sport
        )
        
        # Create some teams
        self.team1 = Team.objects.create(
            name="Lakers",
            abbreviation="LAL",
            sport=self.sport,
            division="male"
        )
        
        self.team2 = Team.objects.create(
            name="Celtics",
            abbreviation="BOS",
            sport=self.sport,
            division="male"
        )

        self.team3 = Team.objects.create(
            name="Warriors",
            abbreviation="GSW", 
            sport=self.sport,
            division="male"
        )
        
        # Create a season (current date is assumed to be May 5, 2025)
        self.today = date(2025, 5, 5)
        self.start_date = self.today - timedelta(days=30)  # April 5, 2025
        self.end_date = self.today + timedelta(days=30)    # June 4, 2025
        
        self.season = Season.objects.create(
            name="2025 Season",
            league=self.league,
            status=Season.Status.UPCOMING,
            start_date=self.start_date,
            end_date=self.end_date
        )
        self.season.teams.add(self.team1, self.team2, self.team3)
        
    def test_season_creation(self):
        """Test that season objects are created correctly"""
        self.assertEqual(self.season.name, "2025 Season")
        self.assertEqual(self.season.league, self.league)
        self.assertEqual(self.season.status, Season.Status.UPCOMING)
        self.assertEqual(self.season.start_date, self.start_date)
        self.assertEqual(self.season.end_date, self.end_date)
        self.assertTrue(self.season.is_recorded)
        
        # Check teams were added
        self.assertEqual(self.season.teams.count(), 3)
        self.assertIn(self.team1, self.season.teams.all())
        self.assertIn(self.team2, self.season.teams.all())
        self.assertIn(self.team3, self.season.teams.all())
        
        # Check string representation
        self.assertEqual(str(self.season), "NBA Season 2025")
    
    def test_season_unique_constraint(self):
        """Test that seasons with same league, and name cannot be created"""
        # Try creating another season with same league and name
        with self.assertRaises(Exception):
            Season.objects.create(
                name="2025 Season",
                league=self.league,
                status=Season.Status.UPCOMING,
                start_date=self.start_date,
                end_date=self.end_date
            )
    
    def test_season_status_transitions(self):
        """Test season status transitions functionality"""
        # Season is UPCOMING
        self.assertEqual(self.season.status, Season.Status.UPCOMING)
        
        # Try invalid transitions
        with self.assertRaises(ValidationError):
            self.season.complete_season()
            
        with self.assertRaises(ValidationError):
            self.season.pause_season()
        
        # Valid transition: UPCOMING to ONGOING
        # We need to set the start date to today for this test
        self.season.start_date = self.today
        self.season.save()
        self.season.start_season(current_date=self.today)  # Pass the test's "today" value
        
        self.assertEqual(self.season.status, Season.Status.ONGOING)
        
        # Valid transitions from ONGOING
        self.season.pause_season()
        self.assertEqual(self.season.status, Season.Status.PAUSED)
        
        # Back to ONGOING for further tests
        self.season.status = Season.Status.ONGOING
        self.season.save()
        
        self.season.complete_season()
        self.assertEqual(self.season.status, Season.Status.COMPLETED)
        
        # Test cancel season
        self.season.status = Season.Status.UPCOMING
        self.season.save()
        
        self.season.cancel_season()
        self.assertEqual(self.season.status, Season.Status.CANCELED)

class SeasonStandingsTest(TestCase):
    """Test cases for season standings calculations"""
    
    def setUp(self):
        """Set up test data for season standings tests"""
        # Create basketball sport
        self.sport = Sport.objects.create(
            name="Basketball",
            scoring_type="points",
            max_players_per_team=12,
            max_players_on_field=5,
            has_period=True,
            max_period=4,
            has_tie=False,
            has_overtime=True
        )
        
        # Create a league
        self.league = League.objects.create(
            name="NBA",
            sport=self.sport
        )
        
        # Create some teams
        self.team1 = Team.objects.create(
            name="Lakers",
            abbreviation="LAL",
            sport=self.sport,
            division="male"
        )
        
        self.team2 = Team.objects.create(
            name="Celtics",
            abbreviation="BOS",
            sport=self.sport,
            division="male"
        )

        self.team3 = Team.objects.create(
            name="Warriors",
            abbreviation="GSW", 
            sport=self.sport,
            division="male"
        )
        
        # Create a season
        self.start_date = date(2025, 1, 1)
        self.end_date = date(2025, 6, 30)
        
        self.season = Season.objects.create(
            name="2025 Season",
            league=self.league,
            status=Season.Status.ONGOING,
            start_date=self.start_date,
            end_date=self.end_date
        )
        self.season.teams.add(self.team1, self.team2, self.team3)
        
        # Create some games
        # Lakers vs Celtics (Lakers win)
        self.game1 = Game.objects.create(
            sport=self.sport,
            league=self.league,
            season=self.season,
            home_team=self.team1,
            away_team=self.team2,
            home_team_score=110,
            away_team_score=105,
            status="completed",
            date=date(2025, 2, 1),
        )
        
        # Lakers vs Warriors (Warriors win)
        self.game2 = Game.objects.create(
            sport=self.sport,
            league=self.league,
            season=self.season,
            home_team=self.team1,
            away_team=self.team3,
            home_team_score=95,
            away_team_score=120,
            status="completed",
            date=date(2025, 2, 8),
        )
        
        # Celtics vs Warriors (Celtics win)
        self.game3 = Game.objects.create(
            sport=self.sport,
            league=self.league,
            season=self.season,
            home_team=self.team2,
            away_team=self.team3,
            home_team_score=115,
            away_team_score=110,
            status="completed",
            date=date(2025, 2, 15),
        )
        
        # Create a bracket for the season
        self.bracket = Bracket.objects.create(
            season=self.season,
            winner=self.team1  # Lakers win the championship
        )
        
    def test_season_standings(self):
        """Test season standings calculation"""
        standings = self.season.standings()
        
        # Print standings for visualization
        print("\n===== BASKETBALL STANDINGS =====")
        print(f"\033[1m{'Team':<15} {'MP':<4} {'W':<4} {'L':<4} {'Pts':<4} {'Win%':<6} {'Rank':<4} {'Score F/A'}\033[0m")
        print("-" * 60)
        for team in standings:
            win_percentage = team['wins'] / team['matches_played'] if team['matches_played'] > 0 else 0
            team_id = team['team_id']
            # Calculate points scored and conceded
            scored = 0
            conceded = 0
            for game in Game.objects.filter(season=self.season).filter(home_team_id=team_id):
                scored += game.home_team_score or 0
                conceded += game.away_team_score or 0
            for game in Game.objects.filter(season=self.season).filter(away_team_id=team_id):
                scored += game.away_team_score or 0
                conceded += game.home_team_score or 0
            
            # Color coding based on rank
            rank_color = "\033[92m" if team['rank'] == 1 else "\033[93m" if team['rank'] == 2 else "\033[91m"
            
            print(f"{rank_color}{team['team_name']:<15} {team['matches_played']:<4} {team['wins']:<4} {team['losses']:<4} {team['points']:<4} {win_percentage:.3f} {team['rank']:<4} {scored:>3}/{conceded:<3}\033[0m")
        print("=" * 60)
        
        # Each team should have an entry in the standings
        self.assertEqual(len(standings), 3)
        
        # Find each team's data
        lakers_data = next(s for s in standings if s["team_name"] == "Lakers")
        celtics_data = next(s for s in standings if s["team_name"] == "Celtics")
        warriors_data = next(s for s in standings if s["team_name"] == "Warriors")
        
        # Check Lakers data (1-1 record)
        self.assertEqual(lakers_data["matches_played"], 2)
        self.assertEqual(lakers_data["wins"], 1)
        self.assertEqual(lakers_data["losses"], 1)
        self.assertEqual(lakers_data["points"], 3)
        
        # Check Celtics data (1-1 record)
        self.assertEqual(celtics_data["matches_played"], 2)
        self.assertEqual(celtics_data["wins"], 1)
        self.assertEqual(celtics_data["losses"], 1)
        self.assertEqual(celtics_data["points"], 3)
        
        # Check Warriors data (1-1 record)
        self.assertEqual(warriors_data["matches_played"], 2)
        self.assertEqual(warriors_data["wins"], 1)
        self.assertEqual(warriors_data["losses"], 1)
        self.assertEqual(warriors_data["points"], 3)
        
        # Check that rankings are correctly assigned
        self.assertEqual(lakers_data["rank"], 1)
        self.assertEqual(celtics_data["rank"], 2)  # Ranking based on win percentage and matches played
        self.assertEqual(warriors_data["rank"], 3)
        
    def test_league_standings(self):
        """Test league standings calculation"""
        # Get league standings, providing request=None
        standings = self.league.standings(None)
        
        # Print league standings for visualization
        print("\n===== LEAGUE STANDINGS (ALL-TIME) =====")
        print(f"{'Team':<10} {'Championships':<13} {'Rank':<4}")
        print("-" * 30)
        for team in standings:
            print(f"{team['team_name']:<10} {team['championships']:<13} {team['rank']:<4}")
        print("=================================\n")
        
        # Check that we have standings for all teams
        self.assertEqual(len(standings), 3)
        
        # Check that the Lakers are championship winners
        lakers_data = next(s for s in standings if s["team_name"] == "Lakers")
        self.assertEqual(lakers_data["championships"], 1)
        
        # Others should have 0 championships
        celtics_data = next(s for s in standings if s["team_name"] == "Celtics")
        self.assertEqual(celtics_data["championships"], 0)
        
        warriors_data = next(s for s in standings if s["team_name"] == "Warriors")  
        self.assertEqual(warriors_data["championships"], 0)
        
        # Lakers should be ranked 1st due to championship
        self.assertEqual(lakers_data["rank"], 1)

class VolleyballStandingsTest(TestCase):
    """Test cases for volleyball-specific standings calculations (sets scoring)"""
    
    def setUp(self):
        """Set up test data for volleyball standings tests"""
        # Create volleyball sport
        self.sport = Sport.objects.create(
            name="Volleyball",
            scoring_type="sets",  # Using sets scoring
            max_players_per_team=12,
            max_players_on_field=6,
            has_period=True,
            max_period=5,  # 5 sets max
            has_tie=False,
            has_overtime=False
        )
        
        # Create a league
        self.league = League.objects.create(
            name="NCAA Volleyball",
            sport=self.sport
        )
        
        # Create some teams
        self.team1 = Team.objects.create(
            name="Perpetual",
            abbreviation="UPHSD",
            sport=self.sport,
            division="male"
        )
        
        self.team2 = Team.objects.create(
            name="CSB",
            abbreviation="CSB",
            sport=self.sport,
            division="male"
        )

        self.team3 = Team.objects.create(
            name="Letran",
            abbreviation="LET", 
            sport=self.sport,
            division="male"
        )
        
        # Create a season
        self.start_date = date(2025, 1, 1)
        self.end_date = date(2025, 6, 30)
        
        self.season = Season.objects.create(
            name="NCAA Season 101",
            league=self.league,
            status=Season.Status.ONGOING,
            start_date=self.start_date,
            end_date=self.end_date
        )
        self.season.teams.add(self.team1, self.team2, self.team3)
        
        # Create some games (using sets scoring)
        # Perpetual vs CSB (Perpetual wins 3-1)
        self.game1 = Game.objects.create(
            sport=self.sport,
            league=self.league,
            season=self.season,
            home_team=self.team1,
            away_team=self.team2,
            home_team_score=3,  # 3 sets won
            away_team_score=1,  # 1 set won
            status="completed",
            date=date(2025, 2, 1),
        )
        
        # Perpetual vs Letran (Letran wins 3-2)
        self.game2 = Game.objects.create(
            sport=self.sport,
            league=self.league,
            season=self.season,
            home_team=self.team1,
            away_team=self.team3,  # This was missing
            home_team_score=2,     # 2 sets won
            away_team_score=3,     # 3 sets won
            status="completed",
            date=date(2025, 2, 8),
        )
        
        # CSB vs Letran (CSB wins 3-0)
        self.game3 = Game.objects.create(
            sport=self.sport,
            league=self.league,
            season=self.season,
            home_team=self.team2,
            away_team=self.team3,
            home_team_score=3,  # 3 sets won
            away_team_score=0,  # 0 sets won
            status="completed",
            date=date(2025, 2, 15),
        )
        
    def test_volleyball_standings(self):
        """Test volleyball standings calculation with sets scoring"""
        standings = self.season.standings()
        
        # Print standings for visualization with enhanced formatting
        print("\n" + "=" * 75)
        print("\033[1m\033[94m===== VOLLEYBALL STANDINGS =====\033[0m")
        print(f"\033[1m{'Team':<15} {'MP':<4} {'W':<4} {'L':<4} {'Sets W':<7} {'Sets L':<7} {'Ratio':<7} {'Win%':<6} {'Rank':<4}\033[0m")
        print("-" * 75)
        for team in standings:
            win_percentage = team['wins'] / team['matches_played'] if team['matches_played'] > 0 else 0
            team_id = team['team_id']
            
            # Calculate sets won and lost
            sets_won = 0
            sets_lost = 0
            for game in Game.objects.filter(season=self.season).filter(home_team_id=team_id):
                sets_won += game.home_team_score or 0
                sets_lost += game.away_team_score or 0
            for game in Game.objects.filter(season=self.season).filter(away_team_id=team_id):
                sets_won += game.away_team_score or 0
                sets_lost += game.home_team_score or 0
            
            set_ratio = sets_won/sets_lost if sets_lost > 0 else sets_won
            
            # Colorize output based on rank
            rank_color = "\033[92m" if team['rank'] == 1 else "\033[93m" if team['rank'] == 2 else "\033[91m"
            
            print(f"{team['team_name']:<15} {team['matches_played']:<4} {team['wins']:<4} {team['losses']:<4} " +
                  f"{sets_won:<7} {sets_lost:<7} {set_ratio:.3f}  {win_percentage:.3f} {rank_color}{team['rank']:<4}\033[0m")
        print("=" * 75)
        
        # Each team should have an entry in the standings
        self.assertEqual(len(standings), 3)
        
        # Find each team's data
        perpetual_data = next(s for s in standings if s["team_name"] == "Perpetual")
        csb_data = next(s for s in standings if s["team_name"] == "CSB")
        letran_data = next(s for s in standings if s["team_name"] == "Letran")
        
        # Check Perpetual data
        self.assertEqual(perpetual_data["matches_played"], 2)
        self.assertEqual(perpetual_data["wins"], 1)
        self.assertEqual(perpetual_data["losses"], 1)
        self.assertEqual(perpetual_data["sets_won"], 5)  # 3 + 2
        self.assertEqual(perpetual_data["sets_lost"], 4)  # 1 + 3
        self.assertAlmostEqual(float(perpetual_data["set_ratio"]), 5/4, places=2)
        
        # Check CSB data
        self.assertEqual(csb_data["matches_played"], 2)
        self.assertEqual(csb_data["wins"], 1)
        self.assertEqual(csb_data["losses"], 1)
        self.assertEqual(csb_data["sets_won"], 4)  # 1 + 3
        self.assertEqual(csb_data["sets_lost"], 3)  # 3 + 0
        self.assertAlmostEqual(float(csb_data["set_ratio"]), 4/3, places=2)
        
        # Check Letran data
        self.assertEqual(letran_data["matches_played"], 2)
        self.assertEqual(letran_data["wins"], 1)
        self.assertEqual(letran_data["losses"], 1)
        self.assertEqual(letran_data["sets_won"], 3)  # 3 + 0
        self.assertEqual(letran_data["sets_lost"], 5)  # 2 + 3
        self.assertAlmostEqual(float(letran_data["set_ratio"]), 3/5, places=2)
        
        # Check rankings - based on set ratio
        # CSB should be ranked first with best set ratio (4/3)
        # Perpetual second (5/4)
        # Letran third (3/5)
        self.assertEqual(csb_data["rank"], 1)
        self.assertEqual(perpetual_data["rank"], 2)
        self.assertEqual(letran_data["rank"], 3)
