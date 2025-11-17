from django.contrib import admin
# Register your models here.
from .models import Facility, Reservation


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
	list_display = ("id", "name", "location", "capacity", "is_active")
	search_fields = ("name", "location")


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
	list_display = ("id", "facility", "coach", "start_datetime", "end_datetime", "status")
	list_filter = ("status", "facility")
	search_fields = ("coach__email", "coach__first_name", "coach__last_name")
# Register your models here.
