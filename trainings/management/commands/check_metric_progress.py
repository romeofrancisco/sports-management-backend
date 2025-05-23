from django.core.management.base import BaseCommand
from teams.models import Player
from trainings.models import TrainingMetric, PlayerMetricRecord

class Command(BaseCommand):
    help = 'Display metric progression for a player'

    def add_arguments(self, parser):
        parser.add_argument('--player', type=int, help='Player ID to check metrics for')
        parser.add_argument('--metric', type=str, help='Metric name to check (e.g., "Vertical Jump")')

    def handle(self, *args, **options):
        player_id = options.get('player')
        metric_name = options.get('metric')
        
        if not player_id:
            # Find a player with metrics
            self.stdout.write('No player specified. Finding a player with recorded metrics...')
            players = Player.objects.all()
            for player in players:
                record_count = PlayerMetricRecord.objects.filter(
                    player_training__player=player
                ).count()
                if record_count > 0:
                    player_id = player.pk
                    self.stdout.write(f'Found player {player.user.get_full_name()} with {record_count} metric records')
                    break
        
        if not player_id:
            self.stdout.write(self.style.ERROR('No players found with metric records'))
            return
            
        try:
            player = Player.objects.get(pk=player_id)
        except Player.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Player with ID {player_id} not found'))
            return
            
        self.stdout.write(f'Checking metrics for player: {player.user.get_full_name() or player.user.username}')
        
        if metric_name:
            metrics = TrainingMetric.objects.filter(name__icontains=metric_name)
        else:
            # Basketball metrics
            metrics = TrainingMetric.objects.filter(
                name__in=[
                    "3/4 Court Sprint", 
                    "Vertical Jump", 
                    "Bench Press Reps (185 lbs)", 
                    "Squat Max", 
                    "Yo-Yo Intermittent Recovery Test", 
                    "Suicide Drill Time", 
                    "Shuttle Run (5-10-5)"
                ]
            )
        
        if not metrics.exists():
            self.stdout.write(self.style.ERROR(f'No metrics found matching "{metric_name}"'))
            return
            
        # Display metric progression for each metric
        for metric in metrics:
            self.stdout.write(f'\nMetric: {metric.name} ({metric.unit})')
            self.stdout.write('-' * 50)
            
            records = PlayerMetricRecord.objects.filter(
                player_training__player=player,
                metric=metric
            ).order_by('player_training__session__date')
            
            if not records.exists():
                self.stdout.write(f'No records found for {metric.name}')
                continue
                
            self.stdout.write(f'{"Date":<12} | {"Value":<12} | Change')
            self.stdout.write('-' * 50)
            
            prev_value = None
            for record in records:
                date = record.player_training.session.date.strftime('%Y-%m-%d')
                value = record.value
                
                if prev_value is not None:
                    change = float(value) - float(prev_value)
                    change_percent = (change / float(prev_value)) * 100 if prev_value != 0 else 0
                    change_str = f"{change:+.2f} ({change_percent:+.2f}%)"
                    
                    # Determine if the change is good or bad
                    is_improvement = (metric.is_lower_better and change < 0) or (not metric.is_lower_better and change > 0)
                    change_style = self.style.SUCCESS if is_improvement else self.style.ERROR
                    
                    self.stdout.write(f"{date:<12} | {value:<12} | {change_style(change_str)}")
                else:
                    self.stdout.write(f"{date:<12} | {value:<12} | Initial value")
                
                prev_value = value
