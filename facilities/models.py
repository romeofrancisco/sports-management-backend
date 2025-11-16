from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Q

from users.models import User
from utils.file_uploads import facility_photo_upload_path


class Facility(models.Model):
	name = models.CharField(max_length=255)
	description = models.TextField(blank=True, null=True)
	image = models.ImageField(
		upload_to=facility_photo_upload_path,
		null=True,
		blank=True,
	)
	location = models.CharField(max_length=255, blank=True, null=True)
	capacity = models.PositiveIntegerField(default=0)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self):
		return self.name


class Reservation(models.Model):
	class Status(models.TextChoices):
		PENDING = "pending", "Pending"
		APPROVED = "approved", "Approved"
		REJECTED = "rejected", "Rejected"
		CANCELLED = "cancelled", "Cancelled"

	facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="reservations")
	coach = models.ForeignKey(User, on_delete=models.CASCADE, related_name="coach_reservations")
	requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="requested_reservations")
	start_datetime = models.DateTimeField()
	end_datetime = models.DateTimeField()
	status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
	notes = models.TextField(blank=True, null=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	def clean(self):
		# Basic validation
		if self.end_datetime <= self.start_datetime:
			# Attach error to end_datetime field so API can map it to the form
			raise ValidationError({"end_datetime": "End time must be after start time"})

		# Disallow reservations in the past
		now = timezone.now()
		if self.start_datetime < now:
			raise ValidationError({"start_datetime": "Start time cannot be in the past"})
		if self.end_datetime < now:
			raise ValidationError({"end_datetime": "End time cannot be in the past"})

		# Check for conflicting approved reservations
		overlap_q = Q(facility=self.facility) & Q(start_datetime__lt=self.end_datetime) & Q(end_datetime__gt=self.start_datetime)

		qs = Reservation.objects.filter(overlap_q).exclude(pk=self.pk)

		# If creating/updating to APPROVED, ensure no other APPROVED reservation overlaps
		# If any approved reservation overlaps, mark as a conflict regardless of this instance's status.
		# Attach the error to the date fields so the API/client can show it inline.
		# Check for any overlapping reservations that are APPROVED or PENDING.
		# Note: using `or` in the filter was incorrect; use `status__in`.
		conflict = qs.filter(status__in=[Reservation.Status.APPROVED, Reservation.Status.PENDING]).exists()
		if conflict:
			raise ValidationError({
				"start_datetime": "This reservation conflicts with an existing approved or pending reservation.",
				"end_datetime": "This reservation conflicts with an existing approved or pending reservation.",
			})
    
   

	def save(self, *args, **kwargs):
		# Run clean to validate
		self.full_clean()
		is_new = self.pk is None
		super().save(*args, **kwargs)

		# If approved, reject overlapping pending reservations automatically
		if self.status == Reservation.Status.APPROVED:
			overlap_q = Q(facility=self.facility) & Q(start_datetime__lt=self.end_datetime) & Q(end_datetime__gt=self.start_datetime)
			Reservation.objects.filter(overlap_q).exclude(pk=self.pk).filter(status=Reservation.Status.PENDING).update(status=Reservation.Status.REJECTED)

	def __str__(self):
		return f"Reservation {self.id} - {self.facility.name} ({self.start_datetime} -> {self.end_datetime})"
