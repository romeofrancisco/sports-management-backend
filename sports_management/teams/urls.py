from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TeamViewSet, PlayerViews, CoachViews

router = DefaultRouter()
router.register(r'teams', TeamViewSet)
router.register(r'players', PlayerViews, basename="players")
router.register(r'coaches', CoachViews, basename="coaches")

urlpatterns = [
    path('', include(router.urls)),
]