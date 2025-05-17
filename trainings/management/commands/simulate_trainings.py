from django.core.management.base import BaseCommand
from teams.models import Team, Player, Coach
from trainings.models import TrainingCategory, TrainingSession, PlayerTraining, TrainingMetric, PlayerMetricRecord
from django.utils import timezone
from django.db import transaction
import random
from decimal import Decimal
from datetime import timedelta


class Command(BaseCommand):
    help = 'Simulate training sessions and player metrics to test data and UI'

    def add_arguments(self, parser):
        parser.add_argument('--team', type=int, help='Team ID to simulate trainings for')
        parser.add_argument('--count', type=int, default=5, help='Number of training sessions to simulate')

    def handle(self, *args, **options):
        team_id = options.get('team')
        count = options.get('count', 5)
        
        # Get team
        if team_id:
            try:
                team = Team.objects.get(id=team_id)
            except Team.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Team with ID {team_id} not found'))
                return
        else:
            # Find a team with players
            self.stdout.write('No specific team provided. Finding teams with players...')
            team = Team.objects.filter(players__isnull=False).distinct().first()
            
            if not team:
                self.stdout.write(self.style.ERROR('No teams with players found. Please create teams and players first.'))
                return
        
        self.stdout.write(f'Using team: {team.name}')
        
        # Create a sample training session
        for i in range(count):
            try:
                session = TrainingSession.objects.create(
                    title=f"{team.name} Training {i+1}",
                    description=f"Training session for {team.name}",
                    date=timezone.now().date() - timedelta(days=i),
                    start_time=timezone.datetime.strptime("14:00", "%H:%M").time(),
                    end_time=timezone.datetime.strptime("16:00", "%H:%M").time(),
                    location=f"Training Ground",
                    team=team,
                    training_type=TrainingSession.TrainingType.TEAM,
                    notes=f"Simulated training session for {team.name}"
                )
                
                self.stdout.write(f'Created session: {session.title} on {session.date}')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error creating training session: {str(e)}'))
        
        self.stdout.write(self.style.SUCCESS(f'Successfully created {count} training sessions'))
