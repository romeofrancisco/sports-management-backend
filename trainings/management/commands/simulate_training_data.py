from django.core.management.base import BaseCommand
from teams.models import Team, Player, Coach
from trainings.models import (
    TrainingCategory, TrainingSession, PlayerTraining, 
    TrainingMetric, PlayerMetricRecord, MetricUnit
)
from django.utils import timezone
from django.db import transaction
from django.db.models import Count, Q
import random
from decimal import Decimal
from datetime import timedelta


class Command(BaseCommand):
    help = 'Simulate training sessions and player metrics to test data and UI'    
    def add_arguments(self, parser):
        parser.add_argument('--team', type=int, help='Team ID to simulate trainings for')
        parser.add_argument('--count', type=int, default=5, help='Number of training sessions to simulate')
        parser.add_argument('--players', type=int, default=0, help='Number of players to generate metrics for (0 = all team players)')
        parser.add_argument('--days', type=int, default=30, help='Date range in days for training scheduling')
        parser.add_argument('--attendance-rate', type=float, default=0.8, help='Attendance rate for players (0.0-1.0)')
        parser.add_argument('--metrics-per-player', type=int, default=5, help='Average number of metrics to record per player')
        parser.add_argument('--progress', action='store_true', help='Show progress in player metrics over time')

    def handle(self, *args, **options):        
        team_id = options.get('team')
        count = options.get('count')
        players_count = options.get('players')
        days_range = options.get('days')
        attendance_rate = min(1.0, max(0.0, options.get('attendance_rate')))
        metrics_per_player = options.get('metrics_per_player')
        show_progress = options.get('progress')
        
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
        
        # Get or create training categories
        categories = self._ensure_training_categories()
        
        # Get or create training metrics
        metrics = self._ensure_training_metrics(categories)
        
        if not metrics.exists():
            self.stdout.write(self.style.ERROR('No training metrics found. Please create metrics first.'))
            return
            
        self.stdout.write(f'Found {metrics.count()} training metrics across {categories.count()} categories')
        
        # Get players for this team
        players = Player.objects.filter(team=team)
        if not players.exists():
            self.stdout.write(self.style.ERROR(f'No players found for team {team.name}. Please add players first.'))
            return
            
        if players_count > 0 and players_count < players.count():
            players = random.sample(list(players), players_count)
            
        self.stdout.write(f'Using {len(players)} players from team {team.name}')        # Create training sessions
        self.stdout.write(f'Creating {count} training sessions for {team.name}...')
        sessions_created = 0        # Generate training session dates (3-4 times per week) - FROM TODAY BACKWARDS
        today = timezone.now().date()
        
        # Create a schedule with consistent 3-4 training sessions per week, working backwards
        session_dates = []
        
        # Training days: typically teams train on Mon/Wed/Fri plus sometimes Sat
        # Define possible training days (0 = Monday, 6 = Sunday)
        core_training_days = [0, 2, 4]  # Mon, Wed, Fri
        optional_training_day = 5       # Saturday (for the 4th session)
        
        # Start from today and work backwards week by week
        current_date = today
        sessions_needed = count
        
        while sessions_needed > 0:
            # Find the start of the current week (Monday)
            days_to_monday = current_date.weekday()
            week_start = current_date - timedelta(days=days_to_monday)
            
            # Set up training days for this week (working backwards)
            weekly_sessions = []
            
            # Add core training days (Mon/Wed/Fri) for this week
            for day_offset in core_training_days:
                training_date = week_start + timedelta(days=day_offset)
                if training_date <= today:  # Only include dates up to today
                    weekly_sessions.append(training_date)
            
            # Add optional Saturday session with 60% probability
            if random.random() < 0.6:  # 60% chance of Saturday session
                saturday_date = week_start + timedelta(days=optional_training_day)
                if saturday_date <= today:  # Only include dates up to today
                    weekly_sessions.append(saturday_date)
            
            # Sort weekly sessions in descending order (most recent first)
            weekly_sessions.sort(reverse=True)
            
            # Add sessions for this week (up to what we need)
            for session_date in weekly_sessions:
                if sessions_needed > 0:
                    session_dates.append(session_date)
                    sessions_needed -= 1
                else:
                    break
              # Move to the previous week
            current_date = week_start - timedelta(days=1)  # Go to the previous week's Sunday
        
        # Sort session dates in chronological order (oldest first) for proper progression
        session_dates.sort()
        
        # Limit to the requested count
        session_dates = session_dates[:count]
        
        # If show_progress is False, shuffle the dates to randomize them a bit
        # while still maintaining the 3-4 times per week pattern
        if not show_progress:
            random.shuffle(session_dates)
        
        for i in range(len(session_dates)):
            try:
                with transaction.atomic():
                    # Use the scheduled date
                    session_date = session_dates[i]
                    
                    # Generate random time
                    start_hour = random.choice([8, 9, 10, 14, 15, 16, 17, 18])
                    start_time = timezone.datetime.strptime(f"{start_hour}:00", "%H:%M").time()
                    end_time = timezone.datetime.strptime(f"{start_hour + 2}:00", "%H:%M").time()
                      # Create the training session
                    session = TrainingSession.objects.create(
                        title=f"{team.name} Training {session_date.strftime('%m/%d')}",
                        description=f"Training session for {team.name}",
                        date=session_date,
                        start_time=start_time,
                        end_time=end_time,
                        location=f"Training Ground {random.randint(1, 5)}",
                        team=team,
                        notes=f"Simulated training session for {team.name}"
                    )
                    
                    # Add random categories (1-3)
                    category_list = list(categories)
                    num_categories = random.randint(1, min(3, len(category_list)))
                    selected_categories = random.sample(category_list, num_categories)
                    session.categories.set(selected_categories)                    # Assign random metrics to the session                    # Prefer metrics from the selected categories
                    category_metrics = metrics.filter(category__in=selected_categories)
                    
                    if category_metrics.exists():
                        category_metrics_list = list(category_metrics)
                        # Ensure we don't try to sample more than we have
                        min_metrics = min(3, len(category_metrics_list))
                        max_metrics = min(10, len(category_metrics_list))
                        if min_metrics == max_metrics:
                            # Just use all available metrics
                            selected_metrics = category_metrics_list
                        else:
                            num_metrics = random.randint(min_metrics, max_metrics)
                            selected_metrics = random.sample(category_metrics_list, num_metrics)
                    else:
                        metrics_list = list(metrics)
                        # Ensure we don't try to sample more than we have
                        min_metrics = min(3, len(metrics_list))
                        max_metrics = min(10, len(metrics_list))
                        if min_metrics == max_metrics:                            # Just use all available metrics
                            selected_metrics = metrics_list
                        else:
                            num_metrics = random.randint(min_metrics, max_metrics)
                            selected_metrics = random.sample(metrics_list, num_metrics)
                    
                    session.metrics.set(selected_metrics)
                    
                    # Create player training records with attendance
                    self._create_player_records(session, players, attendance_rate, selected_metrics, metrics_per_player, show_progress)
                    
                    # Update session status based on the session date and time
                    session.update_status()
                    
                    sessions_created += 1
                    self.stdout.write(f'Created session: {session.title} on {session.date} (Status: {session.status})')
            
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error creating training session: {str(e)}'))
        
        self.stdout.write(self.style.SUCCESS(f'Successfully created {sessions_created} training sessions'))

    def _ensure_training_categories(self):
        """Ensure we have training categories for simulation"""
        default_categories = [
            {"name": "Endurance", "description": "Activities focused on stamina and cardiovascular fitness"},
            {"name": "Strength", "description": "Weight training and resistance exercises"},
            {"name": "Speed", "description": "Sprint and acceleration training"},
            {"name": "Agility", "description": "Quick movements and direction changes"},
            {"name": "Technique", "description": "Sport-specific skill development"},
            {"name": "Recovery", "description": "Rest and rehabilitation activities"}
        ]
        
        categories = TrainingCategory.objects.all()
        
        if not categories.exists():
            self.stdout.write('No training categories found. Creating default categories...')
            
            for category_data in default_categories:
                TrainingCategory.objects.create(**category_data)
                
            categories = TrainingCategory.objects.all()
        
        return categories

    def _ensure_training_metrics(self, categories):
        """Ensure we have training metrics for simulation"""
        metrics = TrainingMetric.objects.all()
        
        if not metrics.exists():
            self.stdout.write('No training metrics found. Creating default metrics...')
            
            # Create metric units first
            unit_mappings = {
                'minutes': MetricUnit.objects.get_or_create(code='minutes', name='Minutes')[0],
                'm': MetricUnit.objects.get_or_create(code='m', name='Meters')[0],
                'bpm': MetricUnit.objects.get_or_create(code='bpm', name='Beats Per Minute')[0],
                'kg': MetricUnit.objects.get_or_create(code='kg', name='Kilograms')[0],
                'reps': MetricUnit.objects.get_or_create(code='reps', name='Repetitions')[0],
                'seconds': MetricUnit.objects.get_or_create(code='seconds', name='Seconds')[0],
                'in': MetricUnit.objects.get_or_create(code='in', name='Inches')[0],
            }
            
            default_metrics = [
                # Endurance metrics
                {
                    "name": "5K Run Time", 
                    "description": "Time to complete a 5 kilometer run",
                    "metric_unit": unit_mappings['minutes'],
                    "category": "Endurance",
                    "is_lower_better": True
                },
                {
                    "name": "Cooper Test", 
                    "description": "Distance covered in 12 minutes",
                    "metric_unit": unit_mappings['m'],
                    "category": "Endurance",
                    "is_lower_better": False
                },
                {
                    "name": "Resting Heart Rate", 
                    "description": "Heart rate after 5 minutes of rest",
                    "metric_unit": unit_mappings['bpm'],
                    "category": "Endurance",
                    "is_lower_better": True
                },
                
                # Strength metrics
                {
                    "name": "Bench Press", 
                    "description": "Maximum weight for bench press",
                    "metric_unit": unit_mappings['kg'],
                    "category": "Strength",
                    "is_lower_better": False
                },
                {
                    "name": "Squat", 
                    "description": "Maximum weight for squat",
                    "metric_unit": unit_mappings['kg'],
                    "category": "Strength",
                    "is_lower_better": False
                },
                {
                    "name": "Pull-ups", 
                    "description": "Number of pull-ups completed",
                    "metric_unit": unit_mappings['reps'],
                    "category": "Strength",
                    "is_lower_better": False
                },
                
                # Speed metrics
                {
                    "name": "40m Sprint", 
                    "description": "Time to complete a 40 meter sprint",
                    "metric_unit": unit_mappings['seconds'],
                    "category": "Speed",
                    "is_lower_better": True
                },
            ]
            
            # Create metrics with proper unit relationships
            for metric_data in default_metrics:
                category_name = metric_data.pop('category')
                category = categories.get(name=category_name)
                metric_data['category'] = category
                TrainingMetric.objects.create(**metric_data)
                
            metrics = TrainingMetric.objects.all()
        
        return metrics

    def _create_player_records(self, session, players, attendance_rate, session_metrics, metrics_per_player, show_progress):
        """Create attendance and metric records for players in a session"""
        # Attendance statuses with weighted probabilities
        attendance_options = [
            ('present', attendance_rate),
            ('absent', (1 - attendance_rate) * 0.5),
            ('late', (1 - attendance_rate) * 0.3),
            ('excused', (1 - attendance_rate) * 0.2)
        ]
        
        # Generate attendance records with metrics
        for player in players:
            # Determine attendance status based on probabilities
            status_choices, weights = zip(*attendance_options)
            attendance_status = random.choices(status_choices, weights=weights, k=1)[0]
              # Create player training record
            player_training = PlayerTraining.objects.create(
                player=player,
                session=session,
                attendance_status=attendance_status,
                notes=f"Simulated attendance" if attendance_status != 'present' else ""
            )
            
            # ALL players should have assigned metrics so coaches can track missed training
            # Decide whether to assign player-specific subset or all session metrics
            if random.random() < 0.3:  # 30% chance of player having custom subset of metrics
                # Assign some of the session metrics (at least 3 or 70% of them)
                session_metrics_list = list(session_metrics)
                if session_metrics_list:  # Make sure there are metrics to sample from
                    num_player_metrics = max(3, int(len(session_metrics_list) * 0.7))
                    num_player_metrics = min(num_player_metrics, len(session_metrics_list))
                    player_metrics = random.sample(session_metrics_list, num_player_metrics)
                    player_training.assigned_metrics.set(player_metrics)
                    assigned_player_metrics = player_metrics
                else:
                    assigned_player_metrics = []
            else:
                # Use all session metrics for this player
                player_training.assigned_metrics.set(session_metrics)
                assigned_player_metrics = session_metrics
            
            # Only record actual performance metrics for present or late players
            # Absent/excused players have assigned metrics but no performance records
            if attendance_status in ['present', 'late'] and assigned_player_metrics:
                self._record_metrics_for_player(player_training, assigned_player_metrics, metrics_per_player, show_progress)

    def _record_metrics_for_player(self, player_training, metrics_to_use, metrics_per_player, show_progress):
        """Record metric values for a player from the available metrics"""        # Choose how many metrics to record (random around metrics_per_player)
        metrics_list = list(metrics_to_use)
        if not metrics_list:
            return
        
        # Ensure we don't try to sample more than we have
        if len(metrics_list) <= metrics_per_player:
            # If we have fewer metrics than requested, use all of them
            selected_metrics = metrics_list
        else:
            # Calculate safe range for random selection
            min_metrics = max(1, min(metrics_per_player - 2, len(metrics_list)))
            max_metrics = min(metrics_per_player + 2, len(metrics_list))
            num_metrics = random.randint(min_metrics, max_metrics)
            selected_metrics = random.sample(metrics_list, num_metrics)
          # Get previous records for this player to show realistic progression
        prev_records = {}
        for metric in selected_metrics:
            # Always look for previous records to ensure progression
            prev_record = PlayerMetricRecord.objects.filter(
                player_training__player=player_training.player,
                metric=metric,
                player_training__session__date__lt=player_training.session.date
            ).order_by('-player_training__session__date').first()
            
            if prev_record:
                prev_records[metric.id] = prev_record.value
        
        # Record values for selected metrics
        for metric in selected_metrics:            # Generate realistic values based on metric type and previous value
            value = self._generate_metric_value(metric, prev_records.get(metric.id))
              
            # Create the metric record
            PlayerMetricRecord.objects.create(
                player_training=player_training,
                metric=metric,
                value=value,
                notes="",  # Optional notes                recorded_by=None,  # No coach assigned since we removed coach field
                recorded_at=timezone.now()
            )

    def _generate_metric_value(self, metric, previous_value):
        """Generate a realistic value for a given metric"""
        unit_code = metric.metric_unit.code
        is_lower_better = metric.is_lower_better
        metric_name = metric.name.lower()
        
        # Always use progression when we have a previous value (realistic training progression)
        if previous_value is not None:
            # Calculate improvement - better performance has 70% chance if player has trained before
            improvement = random.random() < 0.7
            prev_val = float(previous_value)
            
            # Apply realistic progression caps to prevent extreme jumps
            return self._apply_realistic_progression(metric, prev_val, improvement, unit_code, metric_name, is_lower_better)
        
        # Generate realistic initial values for first-time measurements
        return self._generate_initial_value(metric, unit_code, metric_name, is_lower_better)
    def _apply_realistic_progression(self, metric, prev_val, improvement, unit_code, metric_name, is_lower_better):
        """Apply realistic progression to existing performance"""
          # For different metrics, we need different progression rates
        if 'vertical jump' in metric_name and unit_code == 'in':
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
        elif '3/4 court sprint' in metric_name and unit_code == 'seconds':
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
            new_value = max(1.0, new_value)  # Can't have negative or zero time
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
            new_value = max(1.0, new_value)  # Can't have negative or zero time
        elif 'bench press reps' in metric_name and unit_code == 'reps':
            # Rep counts increase by small integers
            if improvement:
                # Add 1-2 reps
                change_amount = random.randint(1, 2)
                new_value = prev_val + change_amount
            else:
                # Lose 0-1 reps
                change_amount = random.randint(0, 1)
                new_value = max(1, prev_val - change_amount)
        elif ('squat' in metric_name or 'bench' in metric_name or 'deadlift' in metric_name) and unit_code == 'kg':
            # Weight improvements - realistic progression
            if improvement:
                # Add 1.25-2.5kg per session (realistic strength progression)
                change_amount = random.uniform(1.25, 2.5)
                new_value = prev_val + change_amount
                # Cap at realistic maximums
                if 'squat' in metric_name:
                    new_value = min(new_value, 160)  # Max squat cap
                elif 'bench' in metric_name:
                    new_value = min(new_value, 130)  # Max bench cap
                elif 'deadlift' in metric_name:
                    new_value = min(new_value, 190)  # Max deadlift cap
            else:
                # Small decline or plateau
                change_amount = random.uniform(0, 1.25)
                new_value = max(40, prev_val - change_amount)  # Don't go below 40kg
        elif 'yo-yo' in metric_name and unit_code == 'm':
            # Yo-yo test improvements - endurance progression
            if improvement:
                # Improve by 30-80 meters (realistic endurance gains)
                change_amount = random.randint(30, 80)
                new_value = min(prev_val + change_amount, 3000)  # Cap at 3000m
            else:
                # Decline by 0-30 meters
                change_amount = random.randint(0, 30)
                new_value = max(600, prev_val - change_amount)  # Don't go below 600m
        elif ('pull' in metric_name or 'push' in metric_name) and unit_code == 'reps':
            # Bodyweight exercise progression
            if improvement:
                # Add 1-3 reps realistically
                change_amount = random.randint(1, 3)
                new_value = prev_val + change_amount
                # Cap at realistic maximums
                if 'pull' in metric_name:
                    new_value = min(new_value, 30)  # Max pull-ups
                elif 'push' in metric_name:
                    new_value = min(new_value, 70)  # Max push-ups
            else:
                # Lose 0-2 reps
                change_amount = random.randint(0, 2)
                new_value = max(5, prev_val - change_amount)
        elif 'cooper' in metric_name and unit_code == 'm':
            # Cooper test (12-min run) progression
            if improvement:
                # Improve by 50-150 meters
                change_amount = random.randint(50, 150)
                new_value = min(prev_val + change_amount, 3500)  # Cap at 3500m
            else:
                # Decline by 0-50 meters
                change_amount = random.randint(0, 50)
                new_value = max(2000, prev_val - change_amount)
        elif '5k' in metric_name and unit_code == 'minutes':
            # 5K run time improvements
            if improvement and is_lower_better:
                # Improve by 10-30 seconds (0.17-0.5 minutes)
                change_amount = random.uniform(0.17, 0.5)
                new_value = max(prev_val - change_amount, 15.0)  # Don't go below 15 min
            else:
                # Decline by 0-20 seconds
                change_amount = random.uniform(0, 0.33)
                new_value = min(prev_val + change_amount, 28.0)  # Don't go above 28 min
        elif 'vertical' in metric_name:
            # Vertical jump improvements
            if improvement:
                if unit_code == 'in':
                    # Improve by 0.5-1.5 inches
                    change_amount = random.uniform(0.5, 1.5)
                    new_value = min(prev_val + change_amount, 36.0)  # Cap at 36 inches
                else:  # cm
                    # Improve by 1-3 cm
                    change_amount = random.uniform(1, 3)
                    new_value = min(prev_val + change_amount, 90.0)  # Cap at 90 cm
            else:
                # Small decline
                if unit_code == 'in':
                    change_amount = random.uniform(0, 0.5)
                    new_value = max(prev_val - change_amount, 15.0)
                else:  # cm
                    change_amount = random.uniform(0, 1.5)
                    new_value = max(prev_val - change_amount, 40.0)
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

    def _generate_initial_value(self, metric, unit_code, metric_name, is_lower_better):
        """Generate realistic initial values for first-time measurements"""
        if '3/4 court sprint' in metric_name and unit_code == 'seconds':
            # Basketball 3/4 court sprint is typically 2.8-4.0 seconds
            if is_lower_better:
                return Decimal(str(round(random.uniform(2.8, 4.0), 2)))
            else:
                # If higher is better (though unusual for sprint)
                return Decimal(str(round(random.uniform(3.5, 5.0), 2)))
        elif 'vertical jump' in metric_name and unit_code == 'in':
            # Vertical jump in inches - normal range for athletes is 16-28 inches
            # With some elite players (5% chance) getting 28-36            
            if random.random() < 0.05:  # Elite jumpers
                return Decimal(str(round(random.uniform(28, 36), 1)))
            else:  # Average to good jumpers
                return Decimal(str(round(random.uniform(16, 28), 1)))
        elif 'bench press reps' in metric_name and '185' in metric_name and unit_code == 'reps':
            # Bench press reps at 185 lbs - typical range 5-25
            return Decimal(str(round(random.randint(5, 25), 0)))
        elif 'squat max' in metric_name and unit_code == 'kg':
            # Squat max in kg - typical range for athletes 100-200kg
            return Decimal(str(round(random.uniform(100, 200), 1)))
        elif 'yo-yo' in metric_name and unit_code == 'm':
            # Yo-Yo test distance in meters - typically 400-2500m
            return Decimal(str(round(random.uniform(400, 2500), 0)))
        elif 'suicide' in metric_name and (unit_code == 'seconds' or unit_code == 'sec'):
            # Suicide drill time - typically 25-35 seconds
            return Decimal(str(round(random.uniform(25, 35), 2)))
        elif 'shuttle' in metric_name and '5-10-5' in metric_name:
            # Pro agility 5-10-5 shuttle - typically 4.2-5.8 seconds
            return Decimal(str(round(random.uniform(4.2, 5.8), 2)))
        
        # For other metrics, use realistic athletic performance standards
        if unit_code == 'seconds' or unit_code == 'sec':
            # Sprint times, agility drills etc.
            if 'sprint' in metric_name or '40m' in metric_name:
                # 40m sprint times for athletes: 4.8-6.2 seconds (high school to college level)
                return Decimal(str(round(random.uniform(4.8, 6.2), 2)))
            elif '10m' in metric_name:
                # 10m sprint: 1.6-2.2 seconds
                return Decimal(str(round(random.uniform(1.6, 2.2), 2)))
            elif 'agility' in metric_name or 't-test' in metric_name:
                # T-test agility: 9.0-12.5 seconds for athletes
                return Decimal(str(round(random.uniform(9.0, 12.5), 2)))
            elif 'shuttle' in metric_name:
                # Pro agility shuttle: 4.2-5.8 seconds
                return Decimal(str(round(random.uniform(4.2, 5.8), 2)))
            else:
                # General sprint/agility times
                return Decimal(str(round(random.uniform(8.0, 15.0), 2)))
                
        elif unit_code == 'minutes':
            # Longer running times
            if '5k' in metric_name or '5 k' in metric_name:
                # 5K run times for athletes: 16-25 minutes
                return Decimal(str(round(random.uniform(16.0, 25.0), 2)))
            elif 'mile' in metric_name or '1600' in metric_name:
                # Mile run: 5-8 minutes for athletes
                return Decimal(str(round(random.uniform(5.0, 8.0), 2)))
            else:
                # Other endurance tests
                return Decimal(str(round(random.uniform(3.0, 15.0), 2)))
                
        elif unit_code == 'm' or unit_code == 'meters':
            # Distance measures
            if 'cooper' in metric_name:
                # Cooper test (12-min run): 2200-3200m for athletes
                return Decimal(str(round(random.uniform(2200, 3200), 0)))
            elif 'yo-yo' in metric_name:
                # Yo-Yo test: 800-2800m for athletes
                return Decimal(str(round(random.uniform(800, 2800), 0)))
            else:
                # Other distance measures
                return Decimal(str(round(random.uniform(500, 2000), 0)))
                
        elif unit_code == 'in' or unit_code == 'inches':
            # Vertical jumps in inches
            if 'vertical' in metric_name:
                # Vertical jump for athletes: 18-32 inches (avg 22-26)
                return Decimal(str(round(random.uniform(18, 32), 1)))
            else:
                # Other jump measures
                return Decimal(str(round(random.uniform(15, 30), 1)))
                
        elif unit_code == 'cm' or unit_code == 'centimeters':
            # Jumps in centimeters
            if 'vertical' in metric_name:
                # Vertical jump: 45-80 cm for athletes
                return Decimal(str(round(random.uniform(45, 80), 1)))
            else:
                return Decimal(str(round(random.uniform(40, 85), 1)))
            
        elif unit_code == 'kg' or unit_code == 'kilograms':
            # Weight lifted - realistic for athletes
            if 'bench' in metric_name and 'press' in metric_name:
                # Bench press: 60-120kg for athletes (body weight to 1.5x body weight)
                return Decimal(str(round(random.uniform(60, 120), 1)))
            elif 'squat' in metric_name:
                # Squat: 80-150kg for athletes (1.2x to 2x body weight, assuming 70-75kg athletes)
                return Decimal(str(round(random.uniform(80, 150), 1)))
            elif 'deadlift' in metric_name:
                # Deadlift: 100-180kg for athletes
                return Decimal(str(round(random.uniform(100, 180), 1)))
            elif 'clean' in metric_name or 'snatch' in metric_name:
                # Olympic lifts: 50-110kg for athletes
                return Decimal(str(round(random.uniform(50, 110), 1)))
            else:
                # Other weight exercises
                return Decimal(str(round(random.uniform(40, 120), 1)))
                
        elif unit_code == 'reps' or unit_code == 'repetitions':
            # Count of exercises - realistic for athletes
            if 'pull' in metric_name or 'chin' in metric_name:
                # Pull-ups/chin-ups: 8-25 reps for athletes
                return Decimal(str(round(random.randint(8, 25), 0)))
            elif 'push' in metric_name:
                # Push-ups: 25-60 reps for athletes
                return Decimal(str(round(random.randint(25, 60), 0)))
            elif 'sit' in metric_name or 'crunch' in metric_name:
                # Sit-ups/crunches: 40-80 reps for athletes
                return Decimal(str(round(random.randint(40, 80), 0)))
            elif 'bench' in metric_name and ('185' in metric_name or 'bodyweight' in metric_name):
                # Bench press reps at specific weight: 8-25 reps
                return Decimal(str(round(random.randint(8, 25), 0)))
            else:
                # Other rep-based exercises
                return Decimal(str(round(random.randint(15, 50), 0)))
                
        elif unit_code == 'bpm':
            # Heart rate - realistic for athletes
            if 'resting' in metric_name:
                # Resting heart rate for athletes: 40-65 bpm
                return Decimal(str(round(random.uniform(40, 65), 0)))
            elif 'recovery' in metric_name:
                # Recovery heart rate drop: 15-35 bpm in 1 minute
                return Decimal(str(round(random.uniform(15, 35), 0)))
            elif 'max' in metric_name:
                # Max heart rate: 180-205 bpm for young athletes
                return Decimal(str(round(random.uniform(180, 205), 0)))
            else:
                # Exercise heart rate: 140-185 bpm
                return Decimal(str(round(random.uniform(140, 185), 0)))
                
        elif unit_code == '%' or unit_code == 'percentage':
            # Percentage measures - realistic ranges
            if 'body' in metric_name and 'fat' in metric_name:
                # Body fat percentage for athletes: 6-15%
                return Decimal(str(round(random.uniform(6, 15), 1)))
            elif 'vo2' in metric_name or 'max' in metric_name:
                # VO2 max relative: 45-70 ml/kg/min (as percentage of elite)
                return Decimal(str(round(random.uniform(65, 90), 1)))
            else:
                # Other percentages
                return Decimal(str(round(random.uniform(70, 95), 1)))
            
        elif unit_code == 'rating':
            # Subjective ratings (RPE, etc.)
            return Decimal(str(round(random.uniform(3, 10), 1)))
            
        else:
            # Default for other units
            return Decimal(str(round(random.uniform(1, 100), 1)))
