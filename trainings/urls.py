from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from .team_analytics_views import TeamAnalyticsViewSet

router = DefaultRouter()
router.register(r'metric-units', views.MetricUnitViewSet, basename='metric-units')
router.register(r'categories', views.TrainingCategoryViewSet, basename='training-categories')
router.register(r'metrics', views.TrainingMetricViewSet, basename='training-metrics')
router.register(r'sessions', views.TrainingSessionViewSet, basename='training-sessions')
router.register(r'player-trainings', views.PlayerTrainingViewSet, basename='player-trainings')
router.register(r'metric-records', views.PlayerMetricRecordViewSet, basename='metric-records')
router.register(r'player-progress', views.PlayerProgressViewSet, basename='player-progress')
router.register(r'attendance-analytics', views.AttendanceAnalyticsViewSet, basename='attendance-analytics')
router.register(r'team-analytics', TeamAnalyticsViewSet, basename='team-analytics')

app_name = 'trainings'

urlpatterns = [
    path('trainings/', include(router.urls)),
]
