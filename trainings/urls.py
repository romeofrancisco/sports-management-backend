from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from .team_analytics_views import TeamAnalyticsViewSet

router = DefaultRouter()
router.register(r'metric-units', views.MetricUnitViewSet)
router.register(r'categories', views.TrainingCategoryViewSet)
router.register(r'metrics', views.TrainingMetricViewSet)
router.register(r'sessions', views.TrainingSessionViewSet)
router.register(r'player-trainings', views.PlayerTrainingViewSet)
router.register(r'metric-records', views.PlayerMetricRecordViewSet)
router.register(r'player-progress', views.PlayerProgressViewSet)
router.register(r'attendance-analytics', views.AttendanceAnalyticsViewSet, basename='attendance-analytics')
router.register(r'team-analytics', TeamAnalyticsViewSet, basename='team-analytics')

app_name = 'trainings'

urlpatterns = [
    path('trainings/', include(router.urls)),
]
