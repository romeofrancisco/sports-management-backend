from django.core.management.base import BaseCommand, CommandError
import random
from django.db import transaction

from teams.models import Team, Coach
from django.utils.text import slugify
from sports.models import Sport


class Command(BaseCommand):
    help = 'Create 8 random demo teams across available sports. Coaches optional.'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=8, help='Number of random teams to create (default 8)')
        parser.add_argument('--sport', type=str, help='Sport slug to use for created teams')
        parser.add_argument('--division', type=str, choices=['male', 'female'], help='Force division for created teams')
        parser.add_argument('--head-coach-email', type=str, help='Email of head coach to assign to all teams (optional)')
        parser.add_argument('--assistant-coach-email', type=str, help='Email of assistant coach to assign to all teams (optional)')
        parser.add_argument('--create-head-coach', action='store_true', help='Create a random head coach account for each created team')

    def handle(self, *args, **options):
        count = options.get('count') or 8
        division = options.get('division')
        head_email = options.get('head_coach_email')
        assistant_email = options.get('assistant_coach_email')

        # expanded pools for more varied names
        adjectives = [
            'Red', 'Blue', 'Golden', 'Mighty', 'Rapid', 'Flying', 'Urban', 'Royal', 'Silent', 'Brave',
            'Crimson', 'Emerald', 'Silver', 'Iron', 'Wild', 'Storm', 'Thunder', 'Valiant', 'Sapphire', 'Scarlet',
            'Grand', 'Fierce', 'Bold', 'Noble', 'Swift', 'Electric', 'Cobalt', 'Green', 'Violet', 'Amber',
            'Stealthy', 'Fearless', 'Radiant', 'Shadow', 'Frozen', 'Burning', 'Savage', 'Untamed', 'Luminous', 'Phantom',
            'Infernal', 'Solar', 'Lunar', 'Galactic', 'Mystic', 'Celestial', 'Prime', 'Titanic', 'Onyx', 'Ivory',
            'Obsidian', 'Scarred', 'Unbreakable', 'Relentless', 'Blazing', 'Eternal', 'Majestic', 'Heroic', 'Daring', 'Dominant',
            'Ironclad', 'Venomous', 'Spectral', 'Atomic', 'Regal', 'Turbo'
        ]


        animals = [
            'Lions', 'Tigers', 'Wolves', 'Eagles', 'Hawks', 'Falcons', 'Bulls', 'Sharks', 'Dragons', 'Knights',
            'Panthers', 'Raptors', 'Mustangs', 'Vipers', 'Ravens', 'Bears', 'Warriors', 'Comets', 'Cyclones', 'Stallions',
            'Trailblazers', 'Sentinels', 'Gladiators', 'Pioneers', 'Titans', 'Guardians', 'Pirates', 'Mavericks', 'Hornets', 'Cougars',
            'Cobras', 'Foxes', 'Wizards', 'Giants', 'Samurai', 'Valkyries', 'Legends', 'Phantoms', 'Rebels', 'Warlords',
            'Crusaders', 'Hunters', 'Raiders', 'Stormers', 'Outlaws', 'Predators', 'Rangers', 'Chargers', 'Infernos', 'Demons',
            'Vikings', 'Monarchs', 'Juggernauts', 'Invaders', 'Titans', 'Nomads', 'Phantoms', 'Blizzards', 'Avalanche', 'Scorpions',
            'Barracudas', 'Phoenix', 'Grizzlies', 'Centaurs', 'Serpents', 'Minotaurs'
        ]


        sport_slug = options.get('sport')
        all_sports = list(Sport.objects.all())
        if sport_slug:
            sport_lookup = Sport.objects.filter(slug=sport_slug).first()
            if not sport_lookup:
                raise CommandError(f"Sport with slug '{sport_slug}' not found")
            # limit available sports to the chosen one
            all_sports = [sport_lookup]

        if not all_sports:
            raise CommandError('No sports found in database. Create some sports first.')

        head_coach = None
        assistant_coach = None
        if head_email:
            from users.models import User

            user = User.objects.filter(email=head_email).first()
            if user:
                head_coach = Coach.objects.filter(user=user).first()
        if assistant_email:
            from users.models import User

            user2 = User.objects.filter(email=assistant_email).first()
            if user2:
                assistant_coach = Coach.objects.filter(user=user2).first()

        created = 0
        # name pools for random coach creation (copied from add_team_players)
        male_first_names = [
            'Michael', 'LeBron', 'Kevin', 'Stephen', 'Kobe', 'James', 'Kawhi',
            'Giannis', 'Damian', 'Luka', 'Nikola', 'Joel', 'Jayson', 'Anthony', 'John',
            'Chris', 'Russell', 'Jimmy', 'Paul', 'Devin', 'Trae', 'Zion', 'Ja', 'Karl', 'Andrew',
            'Tyrese', 'Donovan', 'Jamal', 'DeMar', 'Klay', 'Derrick', 'Bradley', 'Ben', 'Victor',
            'Rudy', 'Pascal', 'Marcus', 'Fred', 'Draymond', 'Carmelo'
        ]

        female_first_names = [
            'Diana', 'Sue', 'Maya', 'Candace', 'Lisa', 'Tamika', 'Lauren',
            'Skylar', 'Breanna', 'Elena', 'Napheesa', 'Sabrina', 'Paige', 'Caitlin', 'Angel',
            'Alyssa', 'Chelsea', 'Arike', 'Kelsey', 'Nneka', 'Chiney', 'Brittney', 'Sylvia', 'Tina', 'Sheryl',
            'Renee', 'Monique', 'Natasha', 'Courtney', 'Jonquel', 'DeWanna', 'Allisha', 'Jewell', 'Diamond',
            'Lexie', 'NaLyssa', 'Aliyah', 'Hailey', 'Jordan', 'Destanni'
        ]

        last_names = [
            'Jordan', 'James', 'Durant', 'Curry', 'Bryant', 'Harden', 'Leonard',
            'Antetokounmpo', 'Lillard', 'Doncic', 'Jokic', 'Embiid', 'Tatum', 'Davis', 'Wall',
            'Irving', 'Booker', 'Mitchell', 'Murray', 'Green', 'Westbrook', 'Beal', 'George', 'Brown', 'Smart',
            'Rose', 'Randle', 'Holiday', 'Ball', 'Fox', 'Porter', 'Barnes', 'Wiggins', 'Morant', 'Ingram',
            'Love', 'Howard', 'Young', 'Carter', 'Miller'
        ]

        create_head_coach_flag = options.get('create_head_coach')
        for i in range(1, count + 1):
            sport = random.choice(all_sports)
            team_div = division or random.choice(['male', 'female'])

            name = f"{random.choice(adjectives)} {random.choice(animals)}"
            if Team.objects.filter(name__iexact=name, sport=sport, division=team_div).exists():
                name = f"{name} {i}"

            abbre = ''.join(word[0] for word in name.split())[:3].upper() + str(i)
            abbreviation = abbre[:5]

            # pick coaches who can coach the sport if none provided
            # If --create-head-coach is set, force creating a new coach per team
            ac = assistant_coach
            if create_head_coach_flag:
                hc = None
            else:
                hc = head_coach
                if not hc:
                    candidates = list(Coach.objects.filter(sports=sport))
                    if candidates:
                        hc = random.choice(candidates)
            if not ac:
                candidates2 = list(Coach.objects.filter(sports=sport))
                if candidates2:
                    choices = [c for c in candidates2 if c != hc]
                    if choices:
                        ac = random.choice(choices)

            # generate a random hex color for the team (e.g. #1fa2b3)
            color = "#{:06x}".format(random.randint(0, 0xFFFFFF))

            try:
                with transaction.atomic():
                    # Optionally create a random head coach for this team
                    hc_to_use = hc
                    if not hc_to_use and create_head_coach_flag:
                        # create a random User and Coach profile
                        from django.contrib.auth import get_user_model
                        User = get_user_model()

                        # choose gender based on team division for realism
                        if team_div == 'female':
                            first = random.choice(female_first_names)
                            sex = 'female'
                        else:
                            first = random.choice(male_first_names)
                            sex = 'male'
                        last = random.choice(last_names)

                        # ensure unique email (use slugified team name since team object not yet created)
                        base_email = f"coach_{slugify(name)}_{i}@example.com"
                        email = base_email
                        c = 1
                        while User.objects.filter(email=email).exists():
                            email = f"coach_{slugify(name)}_{i}_{c}@example.com"
                            c += 1

                        # create coach user using manager helper if available
                        try:
                            user = User.objects.create_coach(email=email, first_name=first, last_name=last, sex=sex, is_active=True)
                        except Exception:
                            # fallback to generic create
                            user = User.objects.create(email=email, first_name=first, last_name=last, sex=sex, is_active=True)

                        # create Coach profile and link sport
                        created_coach = Coach.objects.create(user=user)
                        created_coach.sports.add(sport)
                        hc_to_use = created_coach

                    Team.objects.create(
                        name=name,
                        abbreviation=abbreviation,
                        sport=sport,
                        division=team_div,
                        head_coach=hc_to_use,
                        assistant_coach=ac,
                        color=color,
                    )
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"Created team: {name} ({sport.name} / {team_div})"))
            except Exception as e:
                self.stderr.write(f"Failed to create team {name}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Finished. Created {created} teams."))