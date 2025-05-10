from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SportsViewSet, PositionViewSet, SportStatTypeViewSet, FormulaViewSet, LeaderCategoryViewSet

router = DefaultRouter()
router.register(r"sports", SportsViewSet)
router.register(r"positions", PositionViewSet)
router.register(r"sport-stats", SportStatTypeViewSet)
router.register(r"formulas", FormulaViewSet)
router.register(r"leader-categories", LeaderCategoryViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
