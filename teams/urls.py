from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TeamViewSet, CreatePlayerView, CreateCoachView, PlayerViews, CoachViews

router = DefaultRouter()
router.register(r'teams', TeamViewSet)
router.register(r'players', PlayerViews, basename="players")
router.register(r'coaches', CoachViews, basename="coaches")
router.register(r'register-player', CreatePlayerView, basename="create-player")
router.register(r'register-coach', CreateCoachView)

urlpatterns = [
    path('', include(router.urls)),
]