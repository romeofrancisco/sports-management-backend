import random
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.db.models import Count

from sports.models import Sport, SportStatType
from teams.models import Team, Player
from leagues.models import League, Season
from games.models import Game, PlayerStat, StartingLineup, GameSet
from brackets.models import Bracket


class Command(BaseCommand):
    help = 'Simulate multiple games with player statistics to test data and UI'

    def add_arguments(self, parser):
        parser.add_argument('--league', type=int, help='League ID to simulate games for')
        parser.add_argument('--season', type=int, help='Season ID to simulate games for')
        parser.add_argument('--sport', type=int, help='Sport ID to simulate games for')
        parser.add_argument('--count', type=int, default=5, help='Number of games to simulate')
        parser.add_argument('--completed', action='store_true', help='Create completed games (default: scheduled)')
        parser.add_argument('--days', type=int, default=30, help='Date range in days for game scheduling')
        parser.add_argument('--bracket', type=int, help='Simulate games for a specific bracket ID')
        parser.add_argument('--tournament', type=int, help='Simulate games for a specific tournament ID (will find its bracket)')
        parser.add_argument('--round', type=int, help='Simulate games for a specific round in the bracket')
        parser.add_argument('--all-rounds', action='store_true', help='Simulate all rounds in the bracket')

    def handle(self, *args, **options):
        league_id = options.get('league')
        season_id = options.get('season')
        sport_id = options.get('sport')
        count = options.get('count')
        create_completed = options.get('completed')
        days_range = options.get('days')
        bracket_id = options.get('bracket')
        tournament_id = options.get('tournament')
        bracket_round = options.get('round')
        all_rounds = options.get('all_rounds')
        
        # Check if we're simulating bracket games
        if bracket_id:
            return self._simulate_bracket_games(bracket_id, bracket_round, all_rounds)

        # If a tournament id was provided, try to find its bracket and simulate that
        if tournament_id:
            try:
                bracket = Bracket.objects.get(tournament_id=tournament_id)
            except Bracket.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'No bracket found for tournament with ID {tournament_id}'))
                return
            return self._simulate_bracket_games(bracket.id, bracket_round, all_rounds)
        elif season_id:
            try:
                bracket = Bracket.objects.get(season_id=season_id)
            except Bracket.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'No bracket found for season with ID {season_id}'))
                return
            return self._simulate_bracket_games(bracket.id, bracket_round, all_rounds)

            
        # Get sport, teams, and league
        if sport_id:
            sport = Sport.objects.get(id=sport_id)
        elif league_id:
            league = League.objects.get(id=league_id)
            sport = league.sport
        else:
            # Default to first sport with teams
            self.stdout.write('No specific league, season or sport provided. Finding sports with teams...')
            sport = Sport.objects.annotate(team_count=Count('team')).filter(team_count__gt=1).first()
            
            if not sport:
                self.stdout.write(self.style.ERROR('No sports with multiple teams found. Please create teams first.'))
                return
        
        self.stdout.write(f'Using sport: {sport.name}')
        
        # Get teams for this sport
        teams = Team.objects.filter(sport=sport)
        if teams.count() < 2:
            self.stdout.write(self.style.ERROR(f'Not enough teams for sport {sport.name}. Need at least 2 teams.'))
            return
            
        # Get or create a league and season if not specified
        if not league_id and not season_id:
            league, created = League.objects.get_or_create(
                sport=sport,
                name=f"{sport.name} Test League",
                defaults={
                    'description': f'Auto-generated league for {sport.name}',
                    'year': timezone.now().year
                }
            )
            if created:
                self.stdout.write(f'Created league: {league.name}')
            else:
                self.stdout.write(f'Using existing league: {league.name}')

        if not season_id:
            season, created = Season.objects.get_or_create(
                league=league,
                name="Test Season",
                defaults={
                    'start_date': timezone.now().date(),
                    'end_date': (timezone.now() + timedelta(days=60)).date(),
                }
            )
            if created:
                self.stdout.write(f'Created season: {season.name}')
            else:
                self.stdout.write(f'Using existing season: {season.name}')
        else:
            season = Season.objects.get(id=season_id)
            league = season.league

        # Get all stat types for this sport
        stat_types = SportStatType.objects.filter(sport=sport)
        if not stat_types:
            self.stdout.write(self.style.ERROR(f'No stat types defined for {sport.name}. Please create stat types first.'))
            return

        scoring_stats = stat_types.filter(point_value__gt=0)
        if not scoring_stats:
            self.stdout.write(self.style.WARNING(f'No scoring stat types found for {sport.name}. Games will have no points.'))

        # Create games
        self.stdout.write(f'Creating {count} games for {sport.name}...')
        
        games_created = 0
        for _ in range(count):
            # Pick two random teams
            team_list = list(teams)
            random.shuffle(team_list)
            home_team, away_team = team_list[:2]
            
            # Generate random date within range
            game_date = timezone.now() + timedelta(
                days=random.randint(-days_range//2, days_range//2),
                hours=random.randint(0, 23),
                minutes=random.choice([0, 15, 30, 45])
            )
            
            # Create the game
            with transaction.atomic():
                game = Game.objects.create(
                    sport=sport,
                    league=league,
                    season=season,
                    type=Game.Type.LEAGUE,
                    home_team=home_team,
                    away_team=away_team,
                    date=game_date,
                    location=f'Test Venue {random.randint(1, 10)}',
                    status=Game.Status.SCHEDULED
                )
                
                # Create starting lineup
                self._create_starting_lineup(game)
                
                # If we want completed games, simulate the game with stats
                if create_completed:
                    self._simulate_game_play(game, sport, stat_types)
                
                games_created += 1
                self.stdout.write(f'Created game: {home_team} vs {away_team} on {game_date.strftime("%Y-%m-%d")}')
        
        self.stdout.write(self.style.SUCCESS(f'Successfully created {games_created} games'))

    def _simulate_bracket_games(self, bracket_id, round_num=None, all_rounds=False):
        """Simulate games that are part of a bracket"""
        try:
            bracket = Bracket.objects.get(id=bracket_id)
        except Bracket.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Bracket with ID {bracket_id} not found'))
            return
            
        self.stdout.write(f'Simulating games for bracket: {bracket}')
        
        # Get the sport from either season or tournament
        if bracket.season:
            sport = bracket.season.league.sport
        elif bracket.tournament:
            sport = bracket.tournament.sport
        else:
            self.stdout.write(self.style.ERROR('Bracket is not associated with a season or tournament'))
            return
            
        stat_types = SportStatType.objects.filter(sport=sport)
        
        if not stat_types:
            self.stdout.write(self.style.ERROR(f'No stat types defined for {sport.name}. Please create stat types first.'))
            return

        # Get all games from this bracket
        from django.db.models import Q
        games_query = Game.objects.filter(bracket_match__bracket=bracket, status=Game.Status.SCHEDULED)
        
        # Filter by round if specified
        if round_num and not all_rounds:
            games_query = games_query.filter(bracket_match__round__round_number=round_num)
        
        # Get the games to simulate
        games = list(games_query)
        if not games:
            self.stdout.write(self.style.WARNING(f'No scheduled games found for this bracket'))
            return
            
        self.stdout.write(f'Found {len(games)} games to simulate')
        
        # Simulate games in order (important for proper bracket advancement)
        games.sort(key=lambda g: (g.bracket_match.round.round_number, g.date))
        
        games_simulated = 0
        for game in games:
            try:
                with transaction.atomic():
                    # Create starting lineup if needed
                    if not StartingLineup.objects.filter(game=game).exists():
                        self._create_starting_lineup(game)
                    
                    # Simulate the game
                    self._simulate_game_play(game, sport, stat_types)
                    
                    games_simulated += 1
                    self.stdout.write(f'Simulated game {game}: {game.home_team} vs {game.away_team}')
                    
                    # Let the bracket advancement happen naturally via signals
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error simulating game {game}: {str(e)}'))
                
        self.stdout.write(self.style.SUCCESS(f'Successfully simulated {games_simulated} bracket games'))

    def _create_starting_lineup(self, game):
        """Create starting lineup for both teams"""
        sport = game.sport
        max_players = sport.max_players_on_field
        
        for team in [game.home_team, game.away_team]:
            # Get available players - removed the is_active filter
            players = Player.objects.filter(team=team)
            
            if players.count() < max_players:
                self.stdout.write(self.style.WARNING(
                    f'Team {team.name} has only {players.count()} players, but {max_players} needed.'
                ))
                # Create dummy players if needed
                self._create_dummy_players(team, max_players - players.count())
                players = Player.objects.filter(team=team)
            
            # Select random players for starting lineup
            selected_players = random.sample(list(players), min(max_players, players.count()))
            
            # Create starting lineup
            for player in selected_players:
                StartingLineup.objects.create(
                    game=game,
                    team=team,
                    player=player,
                    is_starting=True
                )
    
    def _create_dummy_players(self, team, count):
        """Create dummy players for a team"""
        from django.contrib.auth import get_user_model
        from sports.models import Position
        User = get_user_model()
        
        sport = team.sport
        # Fix: Get positions related to this sport instead of accessing sport.positions
        positions = list(Position.objects.filter(sport=sport))
        
        for i in range(count):
            # Create username and check if it exists
            username = f"dummy_player_{team.id}_{i}"
            
            # Check if username exists and create unique one if needed
            while User.objects.filter(username=username).exists():
                username = f"dummy_player_{team.id}_{i}_{random.randint(1000, 9999)}"
            
            # Create user for the player
            user = User.objects.create(
                username=username,
                first_name=f"Test{i}",
                last_name=f"Player{team.id}-{i}",
                email=f"{username}@example.com",
                # Add any other required User fields
            )
            
            # Select position if available
            pos = random.choice(positions) if positions else None
            
            # Create player with minimum required fields
            player = Player.objects.create(
                user=user,
                team=team,
                jersey_number=random.randint(1, 99),
                sport=sport,
                # Default values for required fields
                year_level=Player.YEAR_LEVEL_CHOICES[0][0],  # First option in choices
                course=Player.COURSE_CHOICES[0][0],  # First option in choices
            )
            
            # Add position if available
            if pos:
                player.position.add(pos)

    def _simulate_game_play(self, game, sport, stat_types):
        """Simulate a completed game with player stats"""
        # Start the game
        game.status = Game.Status.IN_PROGRESS
        # Convert date to datetime if it's a date object, then make timezone-aware
        if hasattr(game.date, 'hour'):  # It's already a datetime
            game.started_at = timezone.make_aware(game.date) if timezone.is_naive(game.date) else game.date
        else:
            # It's a date object, convert to datetime first
            from datetime import datetime, time
            game_datetime = datetime.combine(game.date, time())
            game.started_at = timezone.make_aware(game_datetime)
        game.save()
        
        # Get all players in the starting lineup
        home_players = list(StartingLineup.objects.filter(game=game, team=game.home_team).values_list('player_id', flat=True))
        away_players = list(StartingLineup.objects.filter(game=game, team=game.away_team).values_list('player_id', flat=True))
        
        # Handle differently based on scoring type
        if sport.scoring_type == Sport.SCORING_TYPES.SETS:
            self._simulate_set_based_game(game, sport, stat_types, home_players, away_players)
        else:
            self._simulate_point_based_game(game, sport, stat_types, home_players, away_players)
        
        # Update final score one more time to ensure accuracy
        game.update_scores()
            
        # If scores are tied and sport doesn't allow ties, add a winning point
        if game.home_team_score == game.away_team_score and not sport.has_tie:
            # Decide which team gets the winning point
            winning_team = random.choice([game.home_team, game.away_team])
            
            # Get a random player from the winning team
            player_list = home_players if winning_team == game.home_team else away_players
            player_id = random.choice(player_list)
            player = Player.objects.get(user_id=player_id)
            
            # Get a random scoring stat
            scoring_stats = list(stat_types.filter(point_value__gt=0))
            if scoring_stats:
                stat_type = random.choice(scoring_stats)
                
                # Create the winning point stat
                PlayerStat.objects.create(
                    game=game,
                    player=player,
                    stat_type=stat_type,
                    period=game.current_period
                )
                
                # Update the score to reflect this final point
                game.update_scores()
                
                self.stdout.write(f"Added tie-breaking point for {winning_team.name} in game {game}")
            else:
                # If no scoring stats found, manually update the score
                if winning_team == game.home_team:
                    game.home_team_score += 1
                else:
                    game.away_team_score += 1
                
                self.stdout.write(f"Manually added tie-breaking point for {winning_team.name} in game {game}")
        
        # Complete the game
        game.status = Game.Status.COMPLETED
        # Ensure started_at is timezone-aware before adding timedelta
        if timezone.is_naive(game.started_at):
            game.started_at = timezone.make_aware(game.started_at)
        game.ended_at = game.started_at + timedelta(hours=random.uniform(1.5, 3))
        game.duration = game.ended_at - game.started_at
        
        # Set the winner based on final score
        if game.home_team_score > game.away_team_score:
            game.winner = game.home_team
        elif game.away_team_score > game.home_team_score:
            game.winner = game.away_team
        else:
            # This should only happen if sport.has_tie is True
            assert sport.has_tie, "Tied game detected for a sport that doesn't allow ties"
            game.winner = None  # No winner for a tied game
            
        game.save()

    def _simulate_set_based_game(self, game, sport, stat_types, home_players, away_players):
        """Simulate a set-based game like volleyball or tennis"""
        scoring_stats = list(stat_types.filter(point_value__gt=0))
        win_threshold = sport.win_threshold or 3  # Default to 3 sets to win
        
        # Create first set
        current_set = GameSet.objects.create(
            game=game, 
            period=1,
            home_team_score=0,
            away_team_score=0,
            winner=None
        )
        
        home_sets_won = 0
        away_sets_won = 0
        
        # Play sets until one team reaches win threshold
        while home_sets_won < win_threshold and away_sets_won < win_threshold:
            # Reset scores for new set
            game.home_team_score = 0
            game.away_team_score = 0
            game.save()
            
            # Play the set
            target_score = sport.win_points_threshold or 25  # Default to 25 points
            min_lead = sport.win_margin or 2  # Default to 2 point lead
            
            # Generate random points until set is complete
            while True:
                # Determine which team scores
                scoring_team = random.choices(
                    [game.home_team, game.away_team], 
                    weights=[0.5, 0.5], 
                    k=1
                )[0]
                
                # Get random player from scoring team
                player_list = home_players if scoring_team == game.home_team else away_players
                player_id = random.choice(player_list)
                # Fixed: Use user_id instead of id
                player = Player.objects.get(user_id=player_id)
                
                # Record the stat
                if scoring_stats:
                    stat_type = random.choice(scoring_stats)
                    PlayerStat.objects.create(
                        game=game,
                        player=player,
                        stat_type=stat_type,
                        period=game.current_period
                    )
                
                # Update game score
                game.update_scores()
                
                # Check if set is complete
                if (game.home_team_score >= target_score or game.away_team_score >= target_score) and \
                   abs(game.home_team_score - game.away_team_score) >= min_lead:
                    break
            
            # Update set results
            current_set.home_team_score = game.home_team_score
            current_set.away_team_score = game.away_team_score
            
            if game.home_team_score > game.away_team_score:
                current_set.winner = game.home_team
                home_sets_won += 1
            else:
                current_set.winner = game.away_team
                away_sets_won += 1
            
            current_set.save()
            
            # If not at win threshold, create next set
            if home_sets_won < win_threshold and away_sets_won < win_threshold:
                game.current_period += 1
                game.save()
                
                current_set = GameSet.objects.create(
                    game=game, 
                    period=game.current_period,
                    home_team_score=0,
                    away_team_score=0,
                    winner=None
                )

    def _simulate_point_based_game(self, game, sport, stat_types, home_players, away_players):
        """Simulate a point-based game like basketball"""
        scoring_stats = list(stat_types.filter(point_value__gt=0))
        non_scoring_stats = list(stat_types.filter(point_value=0))
        
        # Determine number of periods
        max_periods = sport.max_period or 4  # Default to 4 periods
        
        for period in range(1, max_periods + 1):
            game.current_period = period
            game.save()
            
            # Generate random number of scoring plays for this period
            num_plays = random.randint(15, 30)  # Adjust based on sport
            
            for _ in range(num_plays):
                # Determine which team scores
                scoring_team = random.choices(
                    [game.home_team, game.away_team], 
                    weights=[0.5, 0.5], 
                    k=1
                )[0]
                
                # Get random player from scoring team
                player_list = home_players if scoring_team == game.home_team else away_players
                player_id = random.choice(player_list)
                player = Player.objects.get(user_id=player_id)
                
                # Record the scoring stat
                if scoring_stats:
                    stat_type = random.choice(scoring_stats)
                    PlayerStat.objects.create(
                        game=game,
                        player=player,
                        stat_type=stat_type,
                        period=period
                    )
            
            # Add some non-scoring stats too (rebounds, assists, etc.)
            if non_scoring_stats:
                for _ in range(random.randint(20, 40)):
                    team = random.choice([game.home_team, game.away_team])
                    player_list = home_players if team == game.home_team else away_players
                    player_id = random.choice(player_list)
                    player = Player.objects.get(user_id=player_id)
                    
                    stat_type = random.choice(non_scoring_stats)
                    PlayerStat.objects.create(
                        game=game,
                        player=player,
                        stat_type=stat_type,
                        period=period
                    )
        
        # Update final score
        game.update_scores()