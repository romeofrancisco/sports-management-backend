from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import (
    GameViewSet, 
    PlayerStatViewSet, 
    SubstitutionViewSet,  # Import the new view
)

router = DefaultRouter()
router.register(r'player-stats', PlayerStatViewSet, basename='player_stat')
router.register(r'games', GameViewSet, basename='game')
router.register(r'substitutions', SubstitutionViewSet, basename='substitution')

urlpatterns = [
    path('', include(router.urls)),
    ]