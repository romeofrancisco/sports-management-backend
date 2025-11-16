from django.urls import path
from .views import (
    FacilityListCreateAPIView,
    FacilityRetrieveUpdateDestroyAPIView,
    ReservationListCreateAPIView,
    ReservationRetrieveUpdateAPIView,
)

urlpatterns = [
    path('facilities/', FacilityListCreateAPIView.as_view(), name='facilities-list-create'),
    path('facilities/<int:pk>/', FacilityRetrieveUpdateDestroyAPIView.as_view(), name='facilities-detail'),
    path('reservations/', ReservationListCreateAPIView.as_view(), name='reservations-list-create'),
    path('reservations/<int:pk>/', ReservationRetrieveUpdateAPIView.as_view(), name='reservations-detail'),
]
