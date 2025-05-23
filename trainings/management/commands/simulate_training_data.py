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
        parser.add_argument('--coach', type=int, help='Coach ID to use for the trainings')
        parser.add_argument('--count', type=int, default=5, help='Number of training sessions to simulate')
        parser.add_argument('--players', type=int, default=0, help='Number of players to generate metrics for (0 = all team players)')
        parser.add_argument('--days', type=int, default=30, help='Date range in days for training scheduling')
        parser.add_argument('--attendance-rate', type=float, default=0.8, help='Attendance rate for players (0.0-1.0)')
        parser.add_argument('--metrics-per-player', type=int, default=5, help='Average number of metrics to record per player')
        parser.add_argument('--progress', action='store_true', help='Show progress in player metrics over time')

    def handle(self, *args, **options):
        team_id = options.get('team')
        coach_id = options.get('coach')
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
        
        # Get coach
        if coach_id:
            try:
                coach = Coach.objects.get(id=coach_id)            
            except Coach.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Coach with ID {coach_id} not found'))
                return
        else:
            # Find a coach for this team or any staff coach
            coach = Coach.objects.filter(
                Q(teams=team) | Q(user__is_staff=True)
            ).first()
        
        if coach:
            self.stdout.write(f'Using coach: {coach.user.get_full_name() or coach.user.username}')
        else:
            self.stdout.write(self.style.WARNING('No coach found. Training sessions will be created without a coach.'))
        
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
            
        self.stdout.write(f'Using {len(players)} players from team {team.name}')
        
        # Create training sessions
        self.stdout.write(f'Creating {count} training sessions for {team.name}...')
        
        sessions_created = 0
          # Generate training session dates (3-4 times per week)
        today = timezone.now().date()
        start_date = today - timedelta(days=days_range)
        
        # Create a schedule with consistent 3-4 training sessions per week
        session_dates = []
        current_date = start_date
        
        # Training days: typically teams train on Mon/Wed/Fri plus sometimes Sat
        # Define possible training days (0 = Monday, 6 = Sunday)
        core_training_days = [0, 2, 4]  # Mon, Wed, Fri
        optional_training_day = 5       # Saturday (for the 4th session)
        
        # Process week by week to ensure proper weekly distribution
        while current_date <= today and len(session_dates) < count:
            # Find the start of the week (Monday)
            days_to_monday = current_date.weekday()
            week_start = current_date - timedelta(days=days_to_monday)
            
            # Set up training days for this week
            weekly_sessions = []
            
            # Add core training days (Mon/Wed/Fri)
            for day_offset in core_training_days:
                training_date = week_start + timedelta(days=day_offset)
                if training_date >= start_date and training_date <= today:
                    weekly_sessions.append(training_date)
            
            # Add optional Saturday session with 60% probability
            if random.random() < 0.6:  # 60% chance of Saturday session
                saturday_date = week_start + timedelta(days=optional_training_day)
                if saturday_date >= start_date and saturday_date <= today:
                    weekly_sessions.append(saturday_date)
            
            # Add this week's sessions to the overall list
            session_dates.extend(weekly_sessions)
            
            # Move to the next week
            current_date = week_start + timedelta(days=7)
        
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
                        coach=coach,
                        training_type=TrainingSession.TrainingType.TEAM,
                        notes=f"Simulated training session for {team.name}"
                    )
                    
                    # Add random categories (1-3)
                    category_list = list(categories)
                    num_categories = random.randint(1, min(3, len(category_list)))
                    selected_categories = random.sample(category_list, num_categories)
                    session.categories.set(selected_categories)
                    
                    # Assign random metrics to the session                    # Prefer metrics from the selected categories
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
                        if min_metrics == max_metrics:
                            # Just use all available metrics
                            selected_metrics = metrics_list
                        else:
                            num_metrics = random.randint(min_metrics, max_metrics)
                            selected_metrics = random.sample(metrics_list, num_metrics)
                    
                    session.metrics.set(selected_metrics)
                    
                    # Create player training records with attendance
                    self._create_player_records(session, players, attendance_rate, selected_metrics, metrics_per_player, show_progress)
                    
                    sessions_created += 1
                    self.stdout.write(f'Created session: {session.title} on {session.date}')
            
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
            
            # Only record metrics for present or late players
            if attendance_status in ['present', 'late']:
                # Decide whether to assign player-specific metrics
                if random.random() < 0.3:  # 30% chance of player having custom metrics
                    # Assign some of the session metrics (at least 3 or 70% of them)
                    session_metrics_list = list(session_metrics)
                    if session_metrics_list:  # Make sure there are metrics to sample from
                        num_player_metrics = max(3, int(len(session_metrics_list) * 0.7))
                        num_player_metrics = min(num_player_metrics, len(session_metrics_list))
                        player_metrics = random.sample(session_metrics_list, num_player_metrics)
                        player_training.assigned_metrics.set(player_metrics)
                        self._record_metrics_for_player(player_training, player_metrics, metrics_per_player, show_progress)
                else:
                    # Use all session metrics
                    self._record_metrics_for_player(player_training, session_metrics, metrics_per_player, show_progress)

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
        
        # Get previous records for this player to show improvement
        prev_records = {}
        if show_progress:
            for metric in selected_metrics:
                prev_record = PlayerMetricRecord.objects.filter(
                    player_training__player=player_training.player,
                    metric=metric,
                    player_training__session__date__lt=player_training.session.date
                ).order_by('-player_training__session__date').first()
                
                if prev_record:
                    prev_records[metric.id] = prev_record.value
        
        # Record values for selected metrics
        for metric in selected_metrics:
            # Generate realistic values based on metric type and previous value
            value = self._generate_metric_value(metric, prev_records.get(metric.id), show_progress)
            
            # Create the metric record
            PlayerMetricRecord.objects.create(                player_training=player_training,
                metric=metric,
                value=value,
                notes="",  # Optional notes
                recorded_by=player_training.session.coach,
                recorded_at=timezone.now()
            )

    def _generate_metric_value(self, metric, previous_value, show_progress):
        """Generate a realistic value for a given metric"""
        unit_code = metric.metric_unit.code
        is_lower_better = metric.is_lower_better
        metric_name = metric.name.lower()
        
        # If we have a previous value and want to show progress, base the new value on the previous one
        if previous_value is not None and show_progress:
            # Calculate improvement - better performance has 70% chance if player has trained before
            improvement = random.random() < 0.7
            prev_val = float(previous_value)
            
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
            elif ('squat max' in metric_name or 'bench press' in metric_name) and unit_code == 'kg':
                # Weight improvements
                if improvement:
                    # Add 2.5 to 5kg
                    change_amount = random.uniform(2.5, 5.0)
                    new_value = prev_val + change_amount
                else:
                    # Lose 0 to 2.5kg
                    change_amount = random.uniform(0, 2.5)
                    new_value = max(5, prev_val - change_amount)
            elif 'yo-yo' in metric_name and unit_code == 'm':
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
        
        # Generate initial values based on metric name and unit
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
        elif 'suicide' in metric_name and unit_code == 'seconds':
            # Suicide drill time - typically 25-35 seconds
            return Decimal(str(round(random.uniform(25, 35), 2)))
        elif 'shuttle' in metric_name and '5-10-5' in metric_name:
            # Pro agility 5-10-5 shuttle - typically 4.2-5.8 seconds
            return Decimal(str(round(random.uniform(4.2, 5.8), 2)))
            
        # For other metrics, use the original logic
        if unit_code == 'seconds':
            # Sprint times, agility drills etc.
            if 'sprint' in metric_name or '40m' in metric_name:
                return Decimal(str(round(random.uniform(4.0, 7.0), 2)))
            elif '10m' in metric_name:
                return Decimal(str(round(random.uniform(1.5, 2.5), 2)))
            elif 'agility' in metric_name or 't-test' in metric_name:
                return Decimal(str(round(random.uniform(8.0, 15.0), 2)))
            elif 'shuttle' in metric_name:
                return Decimal(str(round(random.uniform(20.0, 30.0), 2)))
            else:
                return Decimal(str(round(random.uniform(10.0, 60.0), 2)))
                
        elif unit_code == 'minutes':
            # Longer running times
            if '5k' in metric_name or '5 k' in metric_name:
                return Decimal(str(round(random.uniform(18.0, 30.0), 2)))
            else:
                return Decimal(str(round(random.uniform(3.0, 15.0), 2)))
                
        elif unit_code == 'm' or unit_code == 'meters':
            # Distance measures
            if 'cooper' in metric_name:
                return Decimal(str(round(random.uniform(2000, 3500), 0)))
            else:
                return Decimal(str(round(random.uniform(100, 1000), 0)))
                
        elif unit_code == 'in' or unit_code == 'inches':
            # Jumps in inches
            return Decimal(str(round(random.uniform(16, 28), 1)))
                
        elif unit_code == 'cm' or unit_code == 'centimeters':
            # Usually for jumps
            return Decimal(str(round(random.uniform(30, 80), 1)))
            
        elif unit_code == 'kg' or unit_code == 'kilograms':
            # Weight lifted
            if 'bench' in metric_name:
                return Decimal(str(round(random.uniform(60, 120), 1)))
            elif 'squat' in metric_name:
                return Decimal(str(round(random.uniform(80, 180), 1)))
            else:
                return Decimal(str(round(random.uniform(50, 150), 1)))
                
        elif unit_code == 'reps' or unit_code == 'repetitions':
            # Count of exercises
            if 'pull' in metric_name:
                return Decimal(str(round(random.uniform(5, 20), 0)))
            else:
                return Decimal(str(round(random.uniform(10, 50), 0)))
                
        elif unit_code == 'bpm':
            # Heart rate
            if 'resting' in metric_name:
                return Decimal(str(round(random.uniform(50, 80), 0)))
            elif 'recovery' in metric_name:
                return Decimal(str(round(random.uniform(20, 50), 0)))
            else:
                return Decimal(str(round(random.uniform(120, 190), 0)))
                
        elif unit_code == '%' or unit_code == 'percentage':
            # Percentage measures
            return Decimal(str(round(random.uniform(40, 95), 1)))
            
        elif unit_code == 'rating':
            # Subjective ratings
            return Decimal(str(round(random.uniform(3, 10), 1)))
            
        else:
            # Default for other units
            return Decimal(str(round(random.uniform(1, 100), 1)))
