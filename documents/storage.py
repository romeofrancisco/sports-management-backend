"""
Custom Cloudinary storage backend for documents
Handles different file types appropriately (images vs raw files)
"""
from cloudinary_storage.storage import RawMediaCloudinaryStorage


class DocumentCloudinaryStorage(RawMediaCloudinaryStorage):
    """
    Custom storage for documents that uses 'raw' resource type
    This is necessary for non-image files like .docx, .pdf, .xlsx, etc.
    """
    pass
