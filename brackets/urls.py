from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import BracketViewSet

router = DefaultRouter()
router.register(r'brackets', BracketViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
