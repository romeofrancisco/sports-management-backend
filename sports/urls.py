from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SportsViewSet,
    PositionViewSet,
    SportStatTypeViewSet,
    FormulaViewSet,
)

router = DefaultRouter()
router.register(r"sports", SportsViewSet)
router.register(r"positions", PositionViewSet, basename="positions")
router.register(r"sport-stats", SportStatTypeViewSet)
router.register(r"formulas", FormulaViewSet, basename="formula")

urlpatterns = [
    path("", include(router.urls)),
]
