from django.shortcuts import render
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from .models import Facility, Reservation
from .serializers import FacilitySerializer, ReservationSerializer
from django.utils import timezone
from django.db.models import Case, When, Value, IntegerField, Q

class IsCoachOrAdmin(permissions.BasePermission):
	def has_permission(self, request, view):
		return request.user and request.user.is_authenticated and (request.user.is_coach or request.user.is_admin)


class FacilityListCreateAPIView(generics.ListCreateAPIView):
	queryset = Facility.objects.all()
	serializer_class = FacilitySerializer
	permission_classes = [permissions.IsAuthenticated]

	class FacilityPagination(PageNumberPagination):
		page_size = 20
		page_size_query_param = "page_size"
		max_page_size = 200

	pagination_class = FacilityPagination

	def perform_create(self, serializer):
		# Only admins can create facilities
		if not self.request.user.is_admin:
			raise PermissionDenied("Only admins can create facilities.")
		serializer.save()

	def list(self, request, *args, **kwargs):
		# Support unauthenticated full list fetch for UI selects by passing
		# ?no_pagination=1 (or any truthy value). This returns all facilities
		# in a single response so frontend selects can show all options.
		if request.query_params.get("no_pagination") in ("1", "true", "True"):
			qs = self.filter_queryset(self.get_queryset())
			serializer = self.get_serializer(qs, many=True)
			return Response(serializer.data)
		return super().list(request, *args, **kwargs)


class FacilityRetrieveUpdateDestroyAPIView(generics.RetrieveUpdateDestroyAPIView):
	queryset = Facility.objects.all()
	serializer_class = FacilitySerializer
	permission_classes = [permissions.IsAuthenticated]


class ReservationListCreateAPIView(generics.ListCreateAPIView):
	queryset = Reservation.objects.all().select_related("facility", "coach", "requested_by")
	serializer_class = ReservationSerializer
	permission_classes = [permissions.IsAuthenticated]

	class ReservationPagination(PageNumberPagination):
		page_size = 10
		page_size_query_param = "page_size"
		max_page_size = 100

	pagination_class = ReservationPagination

	def get_queryset(self):
		qs = super().get_queryset()

		# If the requesting user is a coach, restrict results to their reservations
		# unless the client explicitly requests the full, unpaginated list
		# (via ?no_pagination=1). This allows calendar consumers to fetch all
		# reservations while still keeping paginated coach views limited.
		user = getattr(self.request, "user", None)
		no_pagination = self.request.query_params.get("no_pagination") in ("1", "true", "True")
		if user and getattr(user, "is_coach", False) and not no_pagination:
			qs = qs.filter(coach=user)

		now = timezone.now()

		# Auto-expire all outdated pending reservations
		qs.filter(
			status=Reservation.Status.PENDING,
			start_datetime__lt=now
		).update(status=Reservation.Status.EXPIRED)

		# Filtering by facility/coach/status as before
		facility_id = self.request.query_params.get("facility")
		coach_id = self.request.query_params.get("coach")
		status_q = self.request.query_params.get("status")
		q = self.request.query_params.get("q")

		if facility_id:
			qs = qs.filter(facility_id=facility_id)
		if coach_id:
			qs = qs.filter(coach_id=coach_id)
		if status_q:
			qs = qs.filter(status=status_q)
		# Free-text search across facility name/location and coach/requester names
		if q:
			qs = qs.filter(
				Q(facility__name__icontains=q)
				| Q(facility__location__icontains=q)
				| Q(coach__first_name__icontains=q)
				| Q(coach__last_name__icontains=q)
				| Q(requested_by__first_name__icontains=q)
				| Q(requested_by__last_name__icontains=q)
			)

		# Date range filtering
		start_date_str = self.request.query_params.get("start_date")
		end_date_str = self.request.query_params.get("end_date")
		if start_date_str or end_date_str:
			from dateutil import parser as dateparser
			try:
				start_date = None
				end_date = None
				if start_date_str:
					start_date = dateparser.parse(start_date_str)
					if timezone.is_naive(start_date):
						start_date = timezone.make_aware(start_date, timezone.get_current_timezone())
				if end_date_str:
					end_date = dateparser.parse(end_date_str)
					if timezone.is_naive(end_date):
						end_date = timezone.make_aware(end_date, timezone.get_current_timezone())
				if start_date and end_date:
					qs = qs.filter(start_datetime__range=(start_date, end_date))
				elif start_date:
					qs = qs.filter(start_datetime__gte=start_date)
				elif end_date:
					qs = qs.filter(start_datetime__lte=end_date)
			except Exception:
				pass  # Invalid date format, ignore filter

		# Support calendar-style view & date range filtering
		# NOTE: previous behavior applied a default `view=month` which caused
		# the endpoint to return only the current month's reservations when
		# no calendar params were provided. Change to only apply the
		# date-range filter when the client explicitly passes `view` or
		# `date` so the list endpoint returns the full paginated set by
		# default (matching admin list counts).
		view = self.request.query_params.get("view")
		date_str = self.request.query_params.get("date")

		if view is not None or date_str is not None:
			# parse date parameter; default to now
			try:
				if date_str:
					from dateutil import parser as dateparser
					selected_date = dateparser.parse(date_str)
				else:
					selected_date = timezone.now()
			except Exception:
				selected_date = timezone.now()

			# make timezone aware
			if timezone.is_naive(selected_date):
				selected_date = timezone.make_aware(selected_date, timezone.get_current_timezone())

			from datetime import timedelta
			import calendar as _calendar

			v = (view or "month").lower()

			if v == "day":
				start = selected_date.replace(hour=0, minute=0, second=0, microsecond=0)
				end = start + timedelta(days=1)
			elif v == "week":
				start = selected_date - timedelta(days=selected_date.weekday())
				start = start.replace(hour=0, minute=0, second=0, microsecond=0)
				end = start + timedelta(days=7)
			elif v in ("month", "agenda"):
				start = selected_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
				last_day = _calendar.monthrange(start.year, start.month)[1]
				end = start.replace(day=last_day, hour=23, minute=59, second=59)
			elif v == "year":
				start = selected_date.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
				end = selected_date.replace(month=12, day=31, hour=23, minute=59, second=59)
			else:
				start = selected_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
				last_day = _calendar.monthrange(start.year, start.month)[1]
				end = start.replace(day=last_day, hour=23, minute=59, second=59)

			qs = qs.filter(start_datetime__range=(start, end))

		# Order pending reservations first, then by start_datetime.
		# All non-pending reservations keep their chronological order.
		status_order = Case(
			When(status=Reservation.Status.PENDING, then=Value(0)),
			default=Value(1),
			output_field=IntegerField(),
		)

		return qs.annotate(status_order=status_order).order_by("status_order", "-start_datetime")

	def perform_create(self, serializer):
		user = self.request.user
		# If coach creating, set coach to user
		if user.is_coach:
			serializer.save()
		elif user.is_admin:
			# admins must supply a coach_id in payload
			serializer.save()
		else:
			raise permissions.PermissionDenied("Only coaches or admins can create reservations")

	def list(self, request, *args, **kwargs):
		# Support full-list fetch for calendar consumers via ?no_pagination=1
		if request.query_params.get("no_pagination") in ("1", "true", "True"):
			qs = self.filter_queryset(self.get_queryset())
			serializer = self.get_serializer(qs, many=True)
			return Response(serializer.data)
		return super().list(request, *args, **kwargs)


class ReservationRetrieveUpdateAPIView(generics.RetrieveUpdateDestroyAPIView):
	queryset = Reservation.objects.all().select_related("facility", "coach", "requested_by")
	serializer_class = ReservationSerializer
	permission_classes = [permissions.IsAuthenticated]

	def perform_update(self, serializer):
		# Delegate logic to serializer (it enforces admin-only status changes)
		serializer.save()
  
	def get_object(self):
		obj = super().get_object()
		obj.auto_expire()   # check & update if pending and overdue
		return obj


# Create your views here.
