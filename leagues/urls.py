from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import LeagueViewSet, SeasonViewSet

router = DefaultRouter()
router.register(r'leagues', LeagueViewSet, basename='league')

season_router = DefaultRouter()
season_router.register(r'seasons', SeasonViewSet, basename='season')

urlpatterns = [
    path('', include(router.urls)),
    path('leagues/<int:league_pk>/', include(season_router.urls)),
    path('leagues/<int:pk>/add_team/', LeagueViewSet.as_view({'post': 'add_team'})),
    path('leagues/<int:pk>/remove_team/', LeagueViewSet.as_view({'post': 'remove_team'})),
]