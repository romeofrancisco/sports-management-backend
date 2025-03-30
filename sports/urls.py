from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SportsViewSet, PositionViewSet, SportStatTypeViewSet

router = DefaultRouter()
router.register(r'sports', SportsViewSet)
router.register(r'positions', PositionViewSet, basename="positions")
router.register(r'sport-stats', SportStatTypeViewSet)

urlpatterns = [
    path('', include(router.urls)),
]