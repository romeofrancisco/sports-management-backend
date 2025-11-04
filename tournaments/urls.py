from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TournamentViewSet

router = DefaultRouter()
router.register(r'tournaments', TournamentViewSet, basename='tournament')

urlpatterns = [
    path('', include(router.urls)),
    path('tournaments/<int:pk>/add_team/', TournamentViewSet.as_view({'post': 'add_team'})),
    path('tournaments/<int:pk>/remove_team/', TournamentViewSet.as_view({'post': 'remove_team'})),
    path('tournaments/<int:pk>/manage/', TournamentViewSet.as_view({'post': 'manage'})),
]
