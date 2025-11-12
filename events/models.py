from django.db import models


# Create your models here.
class Event(models.Model):
    class STATUS_CHOICES(models.TextChoices):
        UPCOMING = "upcoming", "Upcoming"
        ONGOING = "ongoing", "Ongoing"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
    
    title = models.CharField(max_length=100)
    description = models.TextField(max_length=255)
    # Use DateTimeFields so frontend can POST/receive ISO datetimes directly
    startDate = models.DateTimeField()
    endDate = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES.choices, default=STATUS_CHOICES.UPCOMING)
    created_by = models.ForeignKey("users.User", on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return self.title
