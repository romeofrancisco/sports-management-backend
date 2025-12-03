from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import FolderViewSet, DocumentViewSet, DocumentPermissionViewSet
from .google_views import (
    get_google_auth_url,
    exchange_google_token,
    create_document_in_google_drive,
    upload_to_google_drive,
    sync_from_google_drive,
    delete_google_drive_file,
    get_google_embed_url,
    download_from_google_drive,
    open_document_in_google_drive,
)

router = DefaultRouter()
router.register(r"folders", FolderViewSet, basename="folder")
router.register(r"files", DocumentViewSet, basename="files")
router.register(
    r"permissions", DocumentPermissionViewSet, basename="document-permission"
)

urlpatterns = [
    path("", include(router.urls)),
    # Google Drive OAuth2 endpoints
    path("google/auth/", get_google_auth_url, name="google-auth"),
    path("google/token/", exchange_google_token, name="google-token"),
    path("google/create/", create_document_in_google_drive, name="google-create"),  # New document upload
    path("google/open/", open_document_in_google_drive, name="google-open"),  # Open document in Google Drive
    path("google/upload/", upload_to_google_drive, name="google-upload"),  # Legacy: temp upload for editing
    path("google/sync/", sync_from_google_drive, name="google-sync"),  # Legacy: sync back to Cloudinary
    path("google/delete/", delete_google_drive_file, name="google-delete"),
    path("google/download/<int:document_id>/", download_from_google_drive, name="google-download"),
    path("google/embed/<int:document_id>/", get_google_embed_url, name="google-embed"),
]
