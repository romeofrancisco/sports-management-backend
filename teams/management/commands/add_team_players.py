from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
import random
from teams.models import Team, Player
from sports.models import Position

User = get_user_model()

class Command(BaseCommand):
    help = 'Add random players to teams that have few or no players'

    def add_arguments(self, parser):
        parser.add_argument('--team', type=int, help='ID of a specific team to add players to')
        parser.add_argument('--team_slug', type=str, help='Slug of a specific team to add players to')
        parser.add_argument('--sport', type=int, help='ID of a sport to add players to all its teams')
        parser.add_argument('--players', type=int, default=10, help='Number of players to add to each team')
        parser.add_argument('--min', type=int, default=5, help='Only add players if team has fewer than this number')

    def handle(self, *args, **options):
        team_id = options.get('team')
        team_slug = options.get('team_slug')
        sport_id = options.get('sport')
        player_count = options.get('players')
        min_players = options.get('min')
        
        teams = []
        # Get teams to add players to
        if team_id:
            teams.append(Team.objects.get(id=team_id))
        elif team_slug:
            teams.append(Team.objects.get(slug=team_slug))
        elif sport_id:
            teams.extend(Team.objects.filter(sport_id=sport_id))
        else:
            teams.extend(Team.objects.all())
            
        self.stdout.write(f"Found {len(teams)} teams")
        
        for team in teams:
            existing_players = Player.objects.filter(team=team).count()
            if existing_players >= min_players:
                self.stdout.write(f"Team {team.name} already has {existing_players} players (minimum: {min_players})")
                continue
                
            # Calculate how many players to add
            to_add = player_count - existing_players
            if to_add <= 0:
                continue
                
            self.stdout.write(f"Adding {to_add} players to team {team.name} ({existing_players} existing)")
            self._create_players(team, to_add)
            
        self.stdout.write(self.style.SUCCESS('Players added successfully'))
                
    def _create_players(self, team, count):
        """Create random players for a team"""
        # Get all positions for this sport
        positions = list(Position.objects.filter(sport=team.sport))
        
        # Get existing jersey numbers for this team to avoid duplicates
        existing_numbers = set(Player.objects.filter(team=team).values_list('jersey_number', flat=True))
        available_numbers = [num for num in range(1, 100) if num not in existing_numbers]
        
        # Default player data options
        male_first_names = ['Michael', 'LeBron', 'Kevin', 'Stephen', 'Kobe', 'James', 'Kawhi', 
                           'Giannis', 'Damian', 'Luka', 'Nikola', 'Joel', 'Jayson', 'Anthony', 'John']
        female_first_names = ['Diana', 'Sue', 'Maya', 'Candace', 'Lisa', 'Tamika', 'Lauren', 
                             'Skylar', 'Breanna', 'Elena', 'Napheesa', 'Sabrina', 'Paige', 'Caitlin', 'Angel']
        last_names = ['Jordan', 'James', 'Durant', 'Curry', 'Bryant', 'Harden', 'Leonard',
                      'Antetokounmpo', 'Lillard', 'Doncic', 'Jokic', 'Embiid', 'Tatum', 'Davis', 'Wall']
        
        for i in range(count):
            # Create unique email instead of username
            email = f"player_{team.slug}_{i}@example.com"
            
            # Check if email exists and create unique one if needed
            counter = 1
            while User.objects.filter(email=email).exists():
                email = f"player_{team.slug}_{i}_{counter}@example.com"
                counter += 1
            
            # Pick random names based on team division
            if team.division == 'female':
                first_name = random.choice(female_first_names)
            else:
                first_name = random.choice(male_first_names)
            last_name = random.choice(last_names)
            
            # Create user for the player
            user = User.objects.create(
                email=email,
                first_name=first_name,
                last_name=last_name,
                sex=team.division,  # Set sex to match team division (male/female)
                # Add any other required fields for your User model
                is_active=True,
                # If you need to set a password
                password="pbkdf2_sha256$600000$AZ3evUimRaPKpY9nDQbYtX$jqFp0UoQO6QkFpvQTC8Adoma7VOAWEWjSVpMOTDMuak="  # "password123"
            )
            
            # Pick random jersey number from available numbers
            if available_numbers:
                jersey_number = random.choice(available_numbers)
                available_numbers.remove(jersey_number)
            else:
                # If no available numbers, generate a random one (this might fail due to unique constraint)
                jersey_number = random.randint(1, 99)
            
            # Select position if available
            player = Player.objects.create(
                user=user,
                team=team,
                jersey_number=jersey_number,
                sport=team.sport,
                height=random.randint(165, 210),  # Random height between 165-210 cm
                weight=random.randint(65, 115),   # Random weight between 65-115 kg
                year_level=random.choice([choice[0] for choice in Player.YEAR_LEVEL_CHOICES]),
                course=random.choice([choice[0] for choice in Player.COURSE_CHOICES])
            )
            
            # Add positions (1 or 2 random positions)
            if positions:
                for pos in random.sample(positions, min(len(positions), random.randint(1, 2))):
                    player.position.add(pos)
            
            self.stdout.write(f"Created player: {first_name} {last_name} (#{jersey_number}) - {team.division} division")