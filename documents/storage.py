# Custom storage classes for handling different file types
# Cloudinary requires different resource types for different file formats

from cloudinary_storage.storage import RawMediaCloudinaryStorage
from django.core.files.storage import default_storage


class DocumentCloudinaryStorage:
    """Stub class for migration compatibility"""
    def __init__(self, *args, **kwargs):
        pass
    
    def deconstruct(self):
        return ('documents.storage.DocumentCloudinaryStorage', [], {})


class RawDocumentStorage(RawMediaCloudinaryStorage):
    """
    Storage class for raw documents (PDF, DOCX, DOC, etc.)
    Uses Cloudinary's 'raw' resource type which supports any file format.
    """
    pass
