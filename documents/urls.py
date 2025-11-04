from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import FolderViewSet, DocumentViewSet, DocumentPermissionViewSet
from .syncfusion_views import import_document, export_document, systemClipboard, restrictediting

router = DefaultRouter()
router.register(r'folders', FolderViewSet, basename='folder')
router.register(r'files', DocumentViewSet, basename='files')
router.register(r'permissions', DocumentPermissionViewSet, basename='document-permission')

urlpatterns = [
    path('', include(router.urls)),
    # Syncfusion Document Editor endpoints
    path('editor/import/', import_document, name='import-document'),
    path('editor/export/', export_document, name='export-document'),
    path('editor/SystemClipboard/', systemClipboard, name='system-clipboard'),
    path('editor/RestrictEditing/', restrictediting, name='restrict-editing'),
]
