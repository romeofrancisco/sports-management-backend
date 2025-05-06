from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from leagues.models import League, Season
from brackets.models import Bracket
from teams.models import Team


class Command(BaseCommand):
    help = 'Create a season with a round robin bracket'

    def add_arguments(self, parser):
        parser.add_argument('--league', type=int, required=True, help='League ID')
        parser.add_argument('--name', type=str, help='Season name (default: "Round Robin Season")')

    def handle(self, *args, **options):
        league_id = options['league']
        season_name = options.get('name') or "Round Robin Season"
        
        try:
            league = League.objects.get(id=league_id)
        except League.DoesNotExist:
            self.stderr.write(self.style.ERROR(f'League with ID {league_id} not found'))
            return
            
        # Check if the league has enough teams
        teams = Team.objects.filter(sport=league.sport)
        if teams.count() < 2:
            self.stderr.write(self.style.ERROR(
                f'Not enough teams for league {league.name}. Need at least 2 teams.'
            ))
            return
            
        # Create the season
        now = timezone.now().date()
        current_year = timezone.now().year
        season = Season.objects.create(
            league=league,
            name=season_name,
            year=current_year,
            start_date=now,
            end_date=now + timedelta(days=90),  # 3 month season
            status=Season.Status.UPCOMING  # Using the Status enum instead of is_active
        )
        
        # Add teams to the season
        season.teams.set(teams)
        
        # Create the bracket with round robin type
        bracket = Bracket.objects.create(
            season=season,
            elimination_type=Bracket.ELIMINATION_TYPES.ROUND_ROBIN
        )
        
        self.stdout.write(self.style.SUCCESS(
            f'Successfully created season "{season.name}" with a round robin bracket'
        ))
        self.stdout.write(f'League: {league.name}')
        self.stdout.write(f'Teams: {teams.count()}')
        self.stdout.write(f'Bracket ID: {bracket.id}')