from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TeamViewSet, PlayerViews, CoachViews, SportTeamsViewSet

router = DefaultRouter()
router.register(r'teams', TeamViewSet)
router.register(r'players', PlayerViews, basename="players")
router.register(r'coaches', CoachViews, basename="coaches")

urlpatterns = [
    path('', include(router.urls)),
    path('sports/<slug:sport_slug>/teams/', SportTeamsViewSet.as_view({'get': 'list'}), name='sport-teams'),
    path('sports/<slug:sport_slug>/teams/<int:pk>/', SportTeamsViewSet.as_view({'get': 'retrieve'}), name='sport-team-detail'),
]