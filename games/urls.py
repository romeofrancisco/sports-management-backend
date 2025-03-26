from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import PlayerStatViewSet, GameViewSet

router = DefaultRouter()
router.register(r'player-stats', PlayerStatViewSet, basename='stats')
router.register(r'games', GameViewSet, basename='game')

urlpatterns = [
    path('', include(router.urls)),
]