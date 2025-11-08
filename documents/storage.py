from cloudinary_storage.storage import RawMediaCloudinaryStorage
from cloudinary.uploader import upload as cloudinary_upload
from cloudinary.utils import cloudinary_url
import os

class DocumentCloudinaryStorage(RawMediaCloudinaryStorage):
    """
    Custom Cloudinary storage for documents that:
    - Normalizes path (uses forward slashes)
    - Removes extensions
    - Overwrites existing uploads
    - Invalidates CDN cache automatically
    """

    def _save(self, name, content):
        # Ensure path uses forward slashes and starts with 'media/'
        root, _ = os.path.splitext(name)
        clean_name = root.replace("\\", "/")

        # ✅ Always prepend 'media/' if missing
        if not clean_name.startswith("media/"):
            clean_name = f"media/{clean_name}"

        # Upload to Cloudinary
        result = cloudinary_upload(
            content,
            public_id=clean_name,        # e.g. media/documents/filename
            resource_type="raw",
            overwrite=True,
            invalidate=True,             # purge CDN cache
        )

        # Store upload result for later access (e.g., version tracking)
        self._last_result = result
        return result.get("public_id")

    def url(self, name):
        """Always return the latest Cloudinary URL with versioning."""
        if hasattr(self, "_last_result"):
            result = self._last_result
            public_id = result.get("public_id")
            version = result.get("version")
            file_url, _ = cloudinary_url(
                public_id,
                resource_type="raw",
                version=version,
            )
            return file_url

        return super().url(name)