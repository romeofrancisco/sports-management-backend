from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SportsViewSet, PositionViewSet

router = DefaultRouter()
router.register(r'sports', SportsViewSet)
router.register(r'positions', PositionViewSet)

urlpatterns = [
    path('', include(router.urls)),
]