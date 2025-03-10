from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TeamViewSet, CreatePlayerView, CreateCoachView

router = DefaultRouter()
router.register(r'teams', TeamViewSet)
router.register(r'register-player', CreatePlayerView)
router.register(r'register-coach', CreateCoachView)

urlpatterns = [
    path('', include(router.urls)),
]