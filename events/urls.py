from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
# Register with an empty prefix so the list endpoint is available at /api/events/
router.register(r"", views.EventViewSet, basename="events")

app_name = "events"

urlpatterns = [
    path("events/", include(router.urls)),
]
