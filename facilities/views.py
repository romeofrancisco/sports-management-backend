from django.shortcuts import render
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from .models import Facility, Reservation
from .serializers import FacilitySerializer, ReservationSerializer


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
		page_size = 20
		page_size_query_param = "page_size"
		max_page_size = 100

	pagination_class = ReservationPagination

	def get_queryset(self):
		qs = super().get_queryset()
		facility_id = self.request.query_params.get("facility")
		coach_id = self.request.query_params.get("coach")
		status_q = self.request.query_params.get("status")
		if facility_id:
			qs = qs.filter(facility_id=facility_id)
		if coach_id:
			qs = qs.filter(coach_id=coach_id)
		if status_q:
			qs = qs.filter(status=status_q)
		return qs.order_by("start_datetime")

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


class ReservationRetrieveUpdateAPIView(generics.RetrieveUpdateAPIView):
	queryset = Reservation.objects.all().select_related("facility", "coach", "requested_by")
	serializer_class = ReservationSerializer
	permission_classes = [permissions.IsAuthenticated]

	def perform_update(self, serializer):
		# Delegate logic to serializer (it enforces admin-only status changes)
		serializer.save()


# Create your views here.
