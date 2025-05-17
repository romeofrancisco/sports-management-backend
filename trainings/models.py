from django.db import models
from teams.models import Player, Team, Coach
from django.utils import timezone
import uuid

class TrainingCategory(models.Model):
    """Training categories like 'Endurance', 'Speed', 'Strength', etc."""
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name_plural = "Training Categories"
class TrainingSession(models.Model):
    """Records a training session for a team or individual players"""
    class TrainingType(models.TextChoices):
        TEAM = "team", "Team Training"
        INDIVIDUAL = "individual", "Individual Training"
    
    title = models.CharField(max_length=200)
    session_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    description = models.TextField(blank=True)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    location = models.CharField(max_length=200)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, null=True, blank=True, related_name='training_sessions')    
    coach = models.ForeignKey(Coach, on_delete=models.SET_NULL, null=True, related_name='conducted_sessions')
    training_type = models.CharField(max_length=20, choices=TrainingType.choices, default=TrainingType.TEAM)
    categories = models.ManyToManyField(TrainingCategory, related_name='sessions')
    metrics = models.ManyToManyField('TrainingMetric', related_name='sessions', blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.title} - {self.date}"
    
    class Meta:
        ordering = ['-date', '-start_time']
        
    @property
    def duration_minutes(self):
        """Calculate duration of training in minutes"""
        if not self.start_time or not self.end_time:
            return 0
            
        start_datetime = timezone.datetime.combine(timezone.now().date(), self.start_time)
        end_datetime = timezone.datetime.combine(timezone.now().date(), self.end_time)
        
        if end_datetime < start_datetime:  # Handle sessions that cross midnight
            end_datetime = end_datetime + timezone.timedelta(days=1)
            
        duration = end_datetime - start_datetime
        return int(duration.total_seconds() / 60)

class PlayerTraining(models.Model):
    """Records an individual player's participation in a training session"""
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='training_records')
    session = models.ForeignKey(TrainingSession, on_delete=models.CASCADE, related_name='player_records')
    attendance_status = models.CharField(
        max_length=20,
        choices=[
            ('present', 'Present'),
            ('absent', 'Absent'),
            ('late', 'Late'),
            ('excused', 'Excused Absence'),
            ('pending', 'Pending'),
        ],
        default='pending'
    )
    notes = models.TextField(blank=True)
    assigned_metrics = models.ManyToManyField('TrainingMetric', related_name='assigned_player_trainings', blank=True)
    
    def __str__(self):
        return f"{self.player} - {self.session.title} ({self.session.date})"
    
    class Meta:
        unique_together = ['player', 'session']

class TrainingMetric(models.Model):
    """Metrics that can be tracked during training like 'sprint time', 'vertical jump', etc."""
    UNIT_CHOICES = [
        # Time units
        ('seconds', 'Seconds'),
        ('minutes', 'Minutes'),
        
        # Distance units
        ('cm', 'Centimeters'),
        ('m', 'Meters'),
        ('km', 'Kilometers'),
        ('in', 'Inches'),
        ('ft', 'Feet'),
        
        # Weight units
        ('kg', 'Kilograms'),
        ('lbs', 'Pounds'),
        
        # Other common units
        ('reps', 'Repetitions'),
        ('sets', 'Sets'),
        ('bpm', 'Beats per minute'),
        ('points', 'Points'),
        ('%', 'Percentage'),
        ('rating', 'Rating (1-10)'),
        
        # Allow custom units as well
        ('other', 'Other (specify in description)'),
    ]
    
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=30, choices=UNIT_CHOICES, help_text="The unit of measurement for this metric")
    category = models.ForeignKey(TrainingCategory, on_delete=models.CASCADE, related_name='metrics')
    is_lower_better = models.BooleanField(default=True, help_text="Is a lower value better? True for metrics like 'time'.")
    
    def __str__(self):
        return f"{self.name} ({self.unit})"
    
    @property
    def primary_category(self):
        """Returns the category of the metric (for backwards compatibility)"""
        return self.category

class PlayerMetricRecord(models.Model):
    """Records a specific measurement for a player during a training session"""
    player_training = models.ForeignKey(PlayerTraining, on_delete=models.CASCADE, related_name='metric_records')
    metric = models.ForeignKey(TrainingMetric, on_delete=models.CASCADE, related_name='records')
    value = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(Coach, on_delete=models.SET_NULL, null=True, related_name='recorded_metrics')
    recorded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.player_training.player} - {self.metric.name}: {self.value} {self.metric.unit}"
    
    class Meta:
        ordering = ['-player_training__session__date', 'metric']
    
    @property
    def improvement_from_last(self):
        """Calculate improvement from last recorded value for this player and metric"""
        prev_record = PlayerMetricRecord.objects.filter(
            player_training__player=self.player_training.player,
            metric=self.metric,
            player_training__session__date__lt=self.player_training.session.date
        ).order_by('-player_training__session__date').first()
        
        if not prev_record:
            return None
            
        raw_diff = self.value - prev_record.value
        
        # For metrics where lower is better (like time), negate the difference
        if self.metric.is_lower_better:
            return -raw_diff
        return raw_diff
        
    @property
    def improvement_percentage(self):
        """Calculate percentage improvement from last recorded value"""
        prev_record = PlayerMetricRecord.objects.filter(
            player_training__player=self.player_training.player,
            metric=self.metric,
            player_training__session__date__lt=self.player_training.session.date
        ).order_by('-player_training__session__date').first()
        
        if not prev_record or prev_record.value == 0:
            return None
            
        raw_percentage = ((self.value - prev_record.value) / prev_record.value) * 100
        
        # For metrics where lower is better (like time), negate the percentage
        if self.metric.is_lower_better:
            return -raw_percentage
        return raw_percentage

    @staticmethod
    def team_improvement(team, metric, up_to_date=None):
        """
        Aggregate improvement for all players in a team for a given metric.
        Returns the average improvement_from_last and improvement_percentage for the latest session per player.
        Optionally, only consider records up to a certain date.
        """
        from django.db.models import OuterRef, Subquery, F, Q
        from django.db.models.functions import Coalesce
        from decimal import Decimal

        # Get all players in the team
        players = team.players.all()
        if not players:
            return {"avg_improvement": None, "avg_percentage": None, "count": 0}

        improvements = []
        percentages = []
        for player in players:
            # Get the latest PlayerTraining for this player in this team (optionally up to a date)
            trainings = player.training_records.filter(
                session__team=team,
                session__isnull=False
            )
            if up_to_date:
                trainings = trainings.filter(session__date__lte=up_to_date)
            trainings = trainings.order_by('-session__date')
            latest_training = trainings.first()
            if not latest_training:
                continue
            # Get the latest PlayerMetricRecord for this metric in that training
            record = latest_training.metric_records.filter(metric=metric).order_by('-recorded_at').first()
            if record and record.improvement_from_last is not None and record.improvement_percentage is not None:
                improvements.append(Decimal(record.improvement_from_last))
                percentages.append(Decimal(record.improvement_percentage))
        if not improvements:
            return {"avg_improvement": None, "avg_percentage": None, "count": 0}
        avg_improvement = sum(improvements) / len(improvements)
        avg_percentage = sum(percentages) / len(percentages)
        return {
            "avg_improvement": float(avg_improvement),
            "avg_percentage": float(avg_percentage),
            "count": len(improvements)
        }
