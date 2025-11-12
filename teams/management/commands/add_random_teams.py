from django.core.management.base import BaseCommand, CommandError
import random
from django.db import transaction
from django.utils.text import slugify
from teams.models import Team, Coach
from sports.models import Sport
import time
import sys

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
        create_head_coach_flag = options.get('create_head_coach')

        # Expanded name pools
        adjectives = ['Red', 'Blue', 'Golden', 'Mighty', 'Rapid', 'Flying', 'Urban', 'Royal']
        animals = ['Lions', 'Tigers', 'Wolves', 'Eagles', 'Hawks', 'Falcons', 'Bulls', 'Sharks']

        male_first_names = ['Michael', 'LeBron', 'Kevin', 'Stephen', 'Kobe', 'James']
        female_first_names = ['Diana', 'Sue', 'Maya', 'Candace', 'Lisa', 'Tamika']
        last_names = ['Jordan', 'James', 'Durant', 'Curry', 'Bryant', 'Harden']

        # Fetch sports
        all_sports = list(Sport.objects.all())
        sport_slug = options.get('sport')
        if sport_slug:
            sport_lookup = Sport.objects.filter(slug=sport_slug).first()
            if not sport_lookup:
                raise CommandError(f"Sport with slug '{sport_slug}' not found")
            all_sports = [sport_lookup]

        if not all_sports:
            raise CommandError('No sports found in database. Create some sports first.')

        # Fetch optional coaches
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
        sys.stdout.write(f"Starting creation of {count} teams...\n")
        sys.stdout.flush()

        for i in range(1, count + 1):
            sport = random.choice(all_sports)
            team_div = division or random.choice(['male', 'female'])
            name = f"{random.choice(adjectives)} {random.choice(animals)}"
            if Team.objects.filter(name__iexact=name, sport=sport, division=team_div).exists():
                name = f"{name} {i}"
            abbreviation = ''.join(word[0] for word in name.split())[:3].upper() + str(i)
            abbreviation = abbreviation[:5]

            ac = assistant_coach
            hc = None if create_head_coach_flag else head_coach
            if not hc and not create_head_coach_flag:
                candidates = list(Coach.objects.filter(sports=sport))
                hc = random.choice(candidates) if candidates else None
            if not ac:
                candidates2 = list(Coach.objects.filter(sports=sport))
                choices = [c for c in candidates2 if c != hc] if candidates2 else []
                ac = random.choice(choices) if choices else None

            color = "#{:06x}".format(random.randint(0, 0xFFFFFF))

            try:
                with transaction.atomic():
                    # Create random head coach if needed
                    hc_to_use = hc
                    if not hc_to_use and create_head_coach_flag:
                        from django.contrib.auth import get_user_model
                        User = get_user_model()
                        if team_div == 'female':
                            first = random.choice(female_first_names)
                            sex = 'female'
                        else:
                            first = random.choice(male_first_names)
                            sex = 'male'
                        last = random.choice(last_names)
                        base_email = f"coach_{slugify(name)}_{i}@example.com"
                        email = base_email
                        c = 1
                        while User.objects.filter(email=email).exists():
                            email = f"coach_{slugify(name)}_{i}_{c}@example.com"
                            c += 1
                        try:
                            user = User.objects.create_coach(email=email, first_name=first, last_name=last, sex=sex, is_active=True)
                        except Exception:
                            user = User.objects.create(email=email, first_name=first, last_name=last, sex=sex, is_active=True)
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

                    # Show progress immediately
                    sys.stdout.write(f"[{i}/{count}] Created team: {name} ({sport.name} / {team_div})\n")
                    sys.stdout.flush()

            except Exception as e:
                sys.stderr.write(f"Failed to create team {name}: {e}\n")
                sys.stderr.flush()

        self.stdout.write(self.style.SUCCESS(f"Finished. Created {created} teams."))
        sys.stdout.flush()
