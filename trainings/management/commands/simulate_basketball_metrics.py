"""
Script to simulate basketball training metrics data
"""
from django.core.management.base import BaseCommand
from teams.models import Team, Player
from trainings.models import TrainingCategory, TrainingSession, PlayerTraining, TrainingMetric, PlayerMetricRecord
from django.utils import timezone
from django.db import transaction
from django.db.models import Count
import random
from decimal import Decimal
from datetime import timedelta


class Command(BaseCommand):
    help = 'Simulate basketball training sessions and metrics'

    def add_arguments(self, parser):
        parser.add_argument('--team', type=int, help='Team ID to simulate trainings for')
        parser.add_argument('--count', type=int, default=5, help='Number of training sessions to simulate')
        parser.add_argument('--days', type=int, default=30, help='Date range in days for training scheduling')
        parser.add_argument('--progress', action='store_true', help='Show progress in player metrics over time')

    def handle(self, *args, **options):
        team_id = options.get('team')
        count = options.get('count', 5)
        days_range = options.get('days', 30)
        show_progress = options.get('progress', False)
        
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
            team = Team.objects.annotate(player_count=Count('players')).filter(player_count__gt=0).first()
            
            if not team:
                self.stdout.write(self.style.ERROR('No teams with players found. Please create teams and players first.'))
                return
        
        self.stdout.write(f'Using team: {team.name}')
        
        # Get players for this team
        players = Player.objects.filter(team=team)
        if not players.exists():
            self.stdout.write(self.style.ERROR(f'No players found for team {team.name}. Please add players first.'))
            return
            
        self.stdout.write(f'Using {players.count()} players from team {team.name}')
        
        # Get basketball training metrics
        b_metrics = self._get_basketball_metrics()
        
        if not b_metrics:
            self.stdout.write(self.style.ERROR('No basketball metrics found. Please run add_basketball_metrics first.'))
            return
            
        self.stdout.write(f'Found {len(b_metrics)} basketball metrics')
        
        # Create training sessions
        self.stdout.write(f'Creating {count} training sessions for {team.name}...')
        
        sessions_created = 0
        
        # If showing progress, ensure dates are in sequence
        if show_progress:
            session_dates = [
                timezone.now().date() - timedelta(days=int(days_range - i*(days_range/count)))
                for i in range(count)
            ]
            # Ensure dates are ordered from past to present
            session_dates.sort()
        else:
            session_dates = []
        
        for i in range(count):
            try:
                with transaction.atomic():
                    # Generate random date or use sequence
                    if show_progress and session_dates:
                        session_date = session_dates[i]
                    else:
                        session_date = timezone.now().date() - timedelta(
                            days=random.randint(0, days_range)
                        )
                    
                    # Generate random time
                    start_hour = random.choice([8, 9, 10, 14, 15, 16, 17, 18])
                    start_time = timezone.datetime.strptime(f"{start_hour}:00", "%H:%M").time()
                    end_time = timezone.datetime.strptime(f"{start_hour + 2}:00", "%H:%M").time()
                    
                    # Create the training session
                    session = TrainingSession.objects.create(
                        title=f"{team.name} Basketball Training {session_date.strftime('%m/%d')}",
                        description=f"Basketball training session for {team.name}",
                        date=session_date,
                        start_time=start_time,
                        end_time=end_time,
                        location=f"Basketball Court {random.randint(1, 3)}",
                        team=team,
                        training_type='TEAM'
                    )
                    
                    # Add selected metrics to the session
                    session.metrics.set(b_metrics)
                    
                    # Create player training records with attendance and metrics
                    self._create_player_records(session, players, b_metrics, show_progress)
                    
                    sessions_created += 1
                    self.stdout.write(f'Created session: {session.title} on {session.date}')
            
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error creating training session: {str(e)}'))
        
        self.stdout.write(self.style.SUCCESS(f'Successfully created {sessions_created} basketball training sessions'))

    def _get_basketball_metrics(self):
        """Get basketball-specific metrics"""
        metric_names = [
            "3/4 Court Sprint",
            "Vertical Jump",
            "Bench Press Reps (185 lbs)",
            "Squat Max",
            "Yo-Yo Intermittent Recovery Test",
            "Suicide Drill Time",
            "Shuttle Run (5-10-5)"
        ]
        
        metrics = list(TrainingMetric.objects.filter(name__in=metric_names))
        return metrics

    def _create_player_records(self, session, players, metrics, show_progress):
        """Create attendance and metric records for players in a session"""
        # Generate attendance records with metrics
        for player in players:
            # Create player training record (all present)
            player_training = PlayerTraining.objects.create(
                player=player,
                session=session,
                attendance_status='present',
                notes=""
            )
            
            # Get previous records for this player to show improvement
            prev_records = {}
            if show_progress:
                for metric in metrics:
                    prev_record = PlayerMetricRecord.objects.filter(
                        player_training__player=player,
                        metric=metric,
                        player_training__session__date__lt=session.date
                    ).order_by('-player_training__session__date').first()
                    
                    if prev_record:
                        prev_records[metric.id] = prev_record.value
            
            # Record values for all metrics
            for metric in metrics:
                # Generate realistic values based on metric type and previous value
                value = self._generate_metric_value(player, metric, prev_records.get(metric.id), show_progress)
                
                # Create the metric record
                PlayerMetricRecord.objects.create(
                    player_training=player_training,
                    metric=metric,
                    value=value,
                    notes="",
                    recorded_at=timezone.now()
                )

    def _generate_metric_value(self, player, metric, previous_value, show_progress):        
        """Generate a realistic value for a given basketball metric"""
        unit = metric.unit
        is_lower_better = metric.is_lower_better
        metric_name = metric.name.lower()
        
        # Generate a player profile factor (some players are naturally better at certain metrics)
        # Use player's primary key to keep it consistent across sessions
        player_factor = random.Random(player.pk + hash(metric_name)).uniform(0.85, 1.15)
        
        # If we have a previous value and want to show progress, base the new value on the previous one
        if previous_value is not None and show_progress:
            # Calculate improvement - better performance has 70% chance if player has trained before
            improvement = random.random() < 0.7
            prev_val = float(previous_value)
            
            # For different metrics, we need different progression rates
            if 'vertical jump' in metric_name and unit == 'in':
                # Vertical jump progresses slowly - only 0.25 to 1 inch per session
                if improvement:
                    # Small improvement - inches progress by small amounts
                    change_amount = random.uniform(0.25, 1.0)
                    new_value = prev_val + change_amount
                else:
                    # Very small decline or no change
                    change_amount = random.uniform(0, 0.25)
                    new_value = prev_val - change_amount
                # Ensure we don't exceed realistic maximums
                new_value = min(new_value, 60.0)
                
            elif '3/4 court sprint' in metric_name:
                # Sprint times improve by small margins
                if improvement and is_lower_better:
                    # Improve by 0.05 to 0.2 seconds if lower is better
                    change_amount = random.uniform(0.05, 0.2)
                    new_value = prev_val - change_amount
                elif improvement and not is_lower_better:
                    # Improve by 0.05 to 0.2 seconds if higher is better
                    change_amount = random.uniform(0.05, 0.2)
                    new_value = prev_val + change_amount
                else:
                    # Small decline
                    change_amount = random.uniform(0, 0.1)
                    if is_lower_better:
                        new_value = prev_val + change_amount
                    else:
                        new_value = prev_val - change_amount
                        
            elif 'suicide' in metric_name or 'shuttle' in metric_name:
                # Similar to sprint but with slightly larger improvements
                if improvement and is_lower_better:
                    change_amount = random.uniform(0.1, 0.3)
                    new_value = prev_val - change_amount
                elif improvement and not is_lower_better:
                    change_amount = random.uniform(0.1, 0.3)
                    new_value = prev_val + change_amount
                else:
                    change_amount = random.uniform(0, 0.15)
                    if is_lower_better:
                        new_value = prev_val + change_amount
                    else:
                        new_value = prev_val - change_amount
                        
            elif 'bench press reps' in metric_name:
                # Rep counts increase by small integers
                if improvement:
                    # Add 1-2 reps
                    change_amount = random.randint(1, 2)
                    new_value = prev_val + change_amount
                else:
                    # Lose 0-1 reps
                    change_amount = random.randint(0, 1)
                    new_value = max(1, prev_val - change_amount)
                    
            elif 'squat max' in metric_name:
                # Weight improvements
                if improvement:
                    # Add 2.5 to 5kg
                    change_amount = random.uniform(2.5, 5.0)
                    new_value = prev_val + change_amount
                else:
                    # Lose 0 to 2.5kg
                    change_amount = random.uniform(0, 2.5)
                    new_value = max(5, prev_val - change_amount)
                    
            elif 'yo-yo' in metric_name:
                # Yo-yo test improves by modest increments
                if improvement:
                    # Improve by 20-50 meters
                    change_amount = random.randint(20, 50)
                    new_value = prev_val + change_amount
                else:
                    # Decline by 0-20 meters
                    change_amount = random.randint(0, 20)
                    new_value = max(100, prev_val - change_amount)
            else:
                # Default progression for other metrics
                if is_lower_better:
                    if improvement:
                        # Improve by 0.5-2%
                        change_percent = random.uniform(0.005, 0.02)
                        new_value = prev_val * (1 - change_percent)
                    else:
                        # Decline by 0-1%
                        change_percent = random.uniform(0, 0.01)
                        new_value = prev_val * (1 + change_percent)
                else:
                    if improvement:
                        # Improve by 0.5-2%
                        change_percent = random.uniform(0.005, 0.02)
                        new_value = prev_val * (1 + change_percent)
                    else:
                        # Decline by 0-1%
                        change_percent = random.uniform(0, 0.01) 
                        new_value = prev_val * (1 - change_percent)
            
            return Decimal(str(round(new_value, 2)))
        
        # Generate initial values based on metric name and unit, with player-specific factor
        if '3/4 court sprint' in metric_name:
            # Basketball 3/4 court sprint is typically 2.8-4.0 seconds
            if is_lower_better:
                base_value = random.uniform(2.8, 4.0) * player_factor
                return Decimal(str(round(base_value, 2)))
            else:
                # If higher is better (though unusual for sprint)
                base_value = random.uniform(3.5, 5.0) * player_factor
                return Decimal(str(round(base_value, 2)))
                
        elif 'vertical jump' in metric_name and unit == 'in':
            # Vertical jump in inches - normal range for athletes is 16-28 inches
            # With some elite players (5% chance) getting 28-36
            if random.random() < 0.05:  # Elite jumpers
                base_value = random.uniform(28, 36) * player_factor
                return Decimal(str(round(base_value, 1)))
            else:  # Average to good jumpers
                base_value = random.uniform(16, 28) * player_factor
                return Decimal(str(round(base_value, 1)))
                
        elif 'bench press reps' in metric_name and '185' in metric_name:
            # Bench press reps at 185 lbs - typical range 5-25
            base_value = random.randint(5, 25) * player_factor
            return Decimal(str(round(base_value, 0)))
            
        elif 'squat max' in metric_name:
            # Squat max in kg - typical range for athletes 100-200kg
            base_value = random.uniform(100, 200) * player_factor
            return Decimal(str(round(base_value, 1)))
            
        elif 'yo-yo' in metric_name:
            # Yo-Yo test distance in meters - typically 400-2500m
            base_value = random.uniform(400, 2500) * player_factor
            return Decimal(str(round(base_value, 0)))
            
        elif 'suicide' in metric_name and unit == 'seconds':
            # Suicide drill time - typically 25-35 seconds
            base_value = random.uniform(25, 35) * player_factor
            return Decimal(str(round(base_value, 2)))
            
        elif 'shuttle' in metric_name and '5-10-5' in metric_name:
            # Pro agility 5-10-5 shuttle - typically 4.2-5.8 seconds
            base_value = random.uniform(4.2, 5.8) * player_factor
            return Decimal(str(round(base_value, 2)))
            
        # Default for other units/metrics
        return Decimal(str(round(random.uniform(1, 100) * player_factor, 1)))
