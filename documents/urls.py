from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import FolderViewSet, DocumentViewSet, DocumentPermissionViewSet

router = DefaultRouter()
router.register(r'folders', FolderViewSet, basename='folder')
router.register(r'files', DocumentViewSet, basename='files')
router.register(r'permissions', DocumentPermissionViewSet, basename='document-permission')

urlpatterns = [
    path('', include(router.urls)),
]
