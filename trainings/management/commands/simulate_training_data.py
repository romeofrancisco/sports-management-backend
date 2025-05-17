from django.core.management.base import BaseCommand
from teams.models import Team, Player, Coach
from trainings.models import TrainingCategory, TrainingSession, PlayerTraining, TrainingMetric, PlayerMetricRecord
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
                Q(team=team) | Q(user__is_staff=True)
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
            
            default_metrics = [
                # Endurance metrics
                {
                    "name": "5K Run Time", 
                    "description": "Time to complete a 5 kilometer run",
                    "unit": "minutes",
                    "category": "Endurance",
                    "is_lower_better": True
                },
                {
                    "name": "Cooper Test", 
                    "description": "Distance covered in 12 minutes",
                    "unit": "m",
                    "category": "Endurance",
                    "is_lower_better": False
                },
                {
                    "name": "Resting Heart Rate", 
                    "description": "Heart rate after 5 minutes of rest",
                    "unit": "bpm",
                    "category": "Endurance",
                    "is_lower_better": True
                },
                
                # Strength metrics
                {
                    "name": "Bench Press", 
                    "description": "Maximum weight for bench press",
                    "unit": "kg",
                    "category": "Strength",
                    "is_lower_better": False
                },
                {
                    "name": "Squat", 
                    "description": "Maximum weight for squat",
                    "unit": "kg",
                    "category": "Strength",
                    "is_lower_better": False
                },
                {
                    "name": "Pull-ups", 
                    "description": "Number of pull-ups completed",
                    "unit": "reps",
                    "category": "Strength",
                    "is_lower_better": False
                },
                
                # Speed metrics
                {
                    "name": "40m Sprint", 
                    "description": "Time to complete a 40 meter sprint",
                    "unit": "seconds",
                    "category": "Speed",
                    "is_lower_better": True
                },
                {
                    "name": "10m Acceleration", 
                    "description": "Time to complete a 10 meter sprint from standing",
                    "unit": "seconds",
                    "category": "Speed",
                    "is_lower_better": True
                },
                
                # Agility metrics
                {
                    "name": "T-Test", 
                    "description": "Time to complete T-test agility drill",
                    "unit": "seconds",
                    "category": "Agility",
                    "is_lower_better": True
                },
                {
                    "name": "Illinois Test", 
                    "description": "Time to complete Illinois agility test",
                    "unit": "seconds",
                    "category": "Agility",
                    "is_lower_better": True
                },
                {
                    "name": "Shuttle Run", 
                    "description": "Time to complete 5x10m shuttle run",
                    "unit": "seconds",
                    "category": "Agility",
                    "is_lower_better": True
                },
                
                # Technique metrics
                {
                    "name": "Passing Accuracy", 
                    "description": "Percentage of successful passes",
                    "unit": "%",
                    "category": "Technique",
                    "is_lower_better": False
                },
                {
                    "name": "Shooting Accuracy", 
                    "description": "Percentage of shots on target",
                    "unit": "%",
                    "category": "Technique",
                    "is_lower_better": False
                },
                {
                    "name": "Dribbling Test", 
                    "description": "Time to complete dribbling course",
                    "unit": "seconds",
                    "category": "Technique",
                    "is_lower_better": True
                },
                
                # Recovery metrics
                {
                    "name": "Recovery Rate", 
                    "description": "Heart rate decrease after 1 minute of rest from exercise",
                    "unit": "bpm",
                    "category": "Recovery",
                    "is_lower_better": False
                },
                {
                    "name": "Sleep Quality", 
                    "description": "Self-reported sleep quality rating",
                    "unit": "rating",
                    "category": "Recovery",
                    "is_lower_better": False
                }
            ]
            
            category_map = {cat.name: cat for cat in categories}
            
            for metric_data in default_metrics:
                category_name = metric_data.pop('category')
                if category_name in category_map:
                    metric_data['category'] = category_map[category_name]
                    TrainingMetric.objects.create(**metric_data)
                else:
                    self.stdout.write(self.style.WARNING(f'Category {category_name} not found, skipping metric'))
                
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
            PlayerMetricRecord.objects.create(
                player_training=player_training,
                metric=metric,
                value=value,
                notes="",  # Optional notes
                recorded_by=player_training.session.coach,
                recorded_at=timezone.now()
            )

    def _generate_metric_value(self, metric, previous_value, show_progress):
        """Generate a realistic value for a given metric"""
        unit = metric.unit
        is_lower_better = metric.is_lower_better
        
        # If we have a previous value and want to show progress, base the new value on the previous one
        if previous_value is not None and show_progress:
            # Calculate improvement - better performance has 70% chance if player has trained before
            improvement = random.random() < 0.7
            
            # For metrics where lower is better, improvement means decreasing the value
            if is_lower_better:
                if improvement:
                    # Improve by 1-5%
                    change_percent = random.uniform(0.01, 0.05)
                    new_value = float(previous_value) * (1 - change_percent)
                else:
                    # Decline by 0-2%
                    change_percent = random.uniform(0, 0.02)
                    new_value = float(previous_value) * (1 + change_percent)
            else:
                if improvement:
                    # Improve by 1-5%
                    change_percent = random.uniform(0.01, 0.05)
                    new_value = float(previous_value) * (1 + change_percent)
                else:
                    # Decline by 0-2%
                    change_percent = random.uniform(0, 0.02) 
                    new_value = float(previous_value) * (1 - change_percent)
            
            return Decimal(str(round(new_value, 2)))
            
        # Generate values based on unit
        if unit == 'seconds':
            # Sprint times, agility drills etc.
            if 'sprint' in metric.name.lower() or '40m' in metric.name.lower():
                return Decimal(str(round(random.uniform(4.0, 7.0), 2)))
            elif '10m' in metric.name.lower():
                return Decimal(str(round(random.uniform(1.5, 2.5), 2)))
            elif 'agility' in metric.name.lower() or 't-test' in metric.name.lower():
                return Decimal(str(round(random.uniform(8.0, 15.0), 2)))
            elif 'shuttle' in metric.name.lower():
                return Decimal(str(round(random.uniform(20.0, 30.0), 2)))
            else:
                return Decimal(str(round(random.uniform(10.0, 60.0), 2)))
                
        elif unit == 'minutes':
            # Longer running times
            if '5k' in metric.name.lower() or '5 k' in metric.name.lower():
                return Decimal(str(round(random.uniform(18.0, 30.0), 2)))
            else:
                return Decimal(str(round(random.uniform(3.0, 15.0), 2)))
                
        elif unit == 'm' or unit == 'meters':
            # Distance measures
            if 'cooper' in metric.name.lower():
                return Decimal(str(round(random.uniform(2000, 3500), 0)))
            else:
                return Decimal(str(round(random.uniform(100, 1000), 0)))
                
        elif unit == 'cm' or unit == 'centimeters':
            # Usually for jumps
            return Decimal(str(round(random.uniform(30, 80), 1)))
            
        elif unit == 'kg' or unit == 'kilograms':
            # Weight lifted
            if 'bench' in metric.name.lower():
                return Decimal(str(round(random.uniform(60, 120), 1)))
            elif 'squat' in metric.name.lower():
                return Decimal(str(round(random.uniform(80, 180), 1)))
            else:
                return Decimal(str(round(random.uniform(50, 150), 1)))
                
        elif unit == 'reps' or unit == 'repetitions':
            # Count of exercises
            if 'pull' in metric.name.lower():
                return Decimal(str(round(random.uniform(5, 20), 0)))
            else:
                return Decimal(str(round(random.uniform(10, 50), 0)))
                
        elif unit == 'bpm':
            # Heart rate
            if 'resting' in metric.name.lower():
                return Decimal(str(round(random.uniform(50, 80), 0)))
            elif 'recovery' in metric.name.lower():
                return Decimal(str(round(random.uniform(20, 50), 0)))
            else:
                return Decimal(str(round(random.uniform(120, 190), 0)))
                
        elif unit == '%' or unit == 'percentage':
            # Percentage measures
            return Decimal(str(round(random.uniform(40, 95), 1)))
            
        elif unit == 'rating':
            # Subjective ratings
            return Decimal(str(round(random.uniform(3, 10), 1)))
            
        else:
            # Default for other units
            return Decimal(str(round(random.uniform(1, 100), 1)))
