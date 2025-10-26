from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import (
    GameViewSet, 
    PlayerStatViewSet, 
    SubstitutionViewSet,
    ScoreUpdateViewSet,
)
from .improvement_views import PlayerImprovementViewSet

router = DefaultRouter()
router.register(r'player-stats', PlayerStatViewSet, basename='player_stat')
router.register(r'games', GameViewSet, basename='game')
router.register(r'substitutions', SubstitutionViewSet, basename='substitution')
router.register(r'player-improvements', PlayerImprovementViewSet, basename='player_improvement')

# Custom URL for score updates with game ID in path
from .views import ScoreUpdateCreateView

urlpatterns = [
    path('', include(router.urls)),
    path('score-updates/<int:game_id>/', ScoreUpdateCreateView.as_view(), name='score_update_create'),
]