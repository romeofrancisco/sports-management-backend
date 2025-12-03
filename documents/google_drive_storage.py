"""
Google Drive Storage Backend for Django
Stores files in Google Drive with folder organization.
Uses a shared folder that the service account has access to.
"""

import os
import uuid
from io import BytesIO
from django.core.files.storage import Storage
from django.core.files.base import ContentFile
from django.utils.deconstruct import deconstructible
from .google_drive_service import get_drive_service


@deconstructible
class GoogleDriveStorage(Storage):
    """
    Django storage backend that stores files in Google Drive.
    Files are uploaded to a shared folder that the service account has editor access to.
    """
    
    # Folder name for player registration documents (created inside the shared folder)
    REGISTRATION_DOCUMENTS_FOLDER_NAME = "Player Registration Documents"
    
    def __init__(self, folder_id=None):
        """
        Initialize Google Drive storage.
        
        Args:
            folder_id: Optional Google Drive folder ID to use as root.
                      If not provided, will use the default shared folder from GoogleDriveService.
        """
        self.folder_id = folder_id
        self._drive_service = None
        self._registration_folder_id = None
    
    @property
    def drive_service(self):
        """Lazy load the drive service"""
        if self._drive_service is None:
            self._drive_service = get_drive_service()
        return self._drive_service
    
    def _get_or_create_registration_folder(self):
        """
        Get or create the registration documents folder inside the shared folder.
        The shared folder (DEFAULT_FOLDER_ID) must have the service account as an editor.
        """
        if self._registration_folder_id:
            return self._registration_folder_id
        
        # Use the default shared folder as parent
        parent_folder_id = self.folder_id or self.drive_service.DEFAULT_FOLDER_ID
        
        # Search for existing folder inside the shared folder
        try:
            query = (
                f"name='{self.REGISTRATION_DOCUMENTS_FOLDER_NAME}' "
                f"and '{parent_folder_id}' in parents "
                f"and mimeType='application/vnd.google-apps.folder' "
                f"and trashed=false"
            )
            results = self.drive_service.drive_service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name)',
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            
            files = results.get('files', [])
            if files:
                self._registration_folder_id = files[0]['id']
                return self._registration_folder_id
        except Exception as e:
            print(f"Error searching for registration folder: {e}")
        
        # Create new folder inside the shared folder
        try:
            file_metadata = {
                'name': self.REGISTRATION_DOCUMENTS_FOLDER_NAME,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_folder_id]
            }
            
            folder = self.drive_service.drive_service.files().create(
                body=file_metadata,
                fields='id, name, webViewLink',
                supportsAllDrives=True
            ).execute()
            
            self._registration_folder_id = folder['id']
            
            # Make folder accessible to anyone with link
            try:
                self.drive_service.share_file(folder['id'], anyone=True, role='reader')
            except Exception as e:
                print(f"Warning: Could not share folder: {e}")
            
            return self._registration_folder_id
        except Exception as e:
            print(f"Error creating registration folder: {e}")
            # Fall back to using the parent folder directly
            self._registration_folder_id = parent_folder_id
            return self._registration_folder_id
    
    def _save(self, name, content):
        """
        Save a file to Google Drive.
        
        Args:
            name: The file name (may include path like 'registration_documents/filename.pdf')
            content: The file content
        
        Returns:
            The Google Drive file ID
        """
        # Extract just the filename from the path
        filename = os.path.basename(name)
        
        # Generate unique filename to avoid conflicts
        name_part, ext = os.path.splitext(filename)
        unique_filename = f"{name_part}_{uuid.uuid4().hex[:8]}{ext}"
        
        # Get the registration folder ID (inside the shared folder)
        folder_id = self._get_or_create_registration_folder()
        
        # Read file content
        if hasattr(content, 'read'):
            file_content = content.read()
            if hasattr(content, 'seek'):
                content.seek(0)
        else:
            file_content = content
        
        # Detect MIME type
        mime_type = self._get_mime_type(ext)
        
        # Upload to Google Drive - don't convert to Google format, keep original
        file_info = self.drive_service.upload_file(
            file_content=file_content,
            filename=unique_filename,
            mime_type=mime_type,
            convert_to_google=False,  # Keep original format
            folder_id=folder_id
        )
        
        # Share file for viewing
        try:
            self.drive_service.share_file(file_info['id'], anyone=True, role='reader')
        except Exception as e:
            print(f"Warning: Could not share file: {e}")
        
        # Return the Google Drive file ID as the "name"
        return file_info['id']
    
    def _open(self, name, mode='rb'):
        """
        Open a file from Google Drive.
        
        Args:
            name: The Google Drive file ID
            mode: File mode (only 'rb' supported)
        
        Returns:
            File-like object
        """
        file_content = self.drive_service.download_file(name)
        return ContentFile(file_content)
    
    def delete(self, name):
        """
        Delete a file from Google Drive.
        
        Args:
            name: The Google Drive file ID
        """
        try:
            self.drive_service.delete_file(name)
        except Exception as e:
            print(f"Error deleting file from Google Drive: {e}")
    
    def exists(self, name):
        """
        Check if a file exists in Google Drive.
        
        Args:
            name: The Google Drive file ID
        
        Returns:
            bool
        """
        try:
            self.drive_service.get_file(name)
            return True
        except Exception:
            return False
    
    def url(self, name):
        """
        Get the URL for viewing a file.
        
        Args:
            name: The Google Drive file ID
        
        Returns:
            URL string for viewing the file
        """
        if not name:
            return None
        
        # Direct view link
        return f"https://drive.google.com/file/d/{name}/view"
    
    def get_embed_url(self, name):
        """
        Get embeddable preview URL for a file.
        
        Args:
            name: The Google Drive file ID
        
        Returns:
            URL string for embedding in iframe
        """
        if not name:
            return None
        return f"https://drive.google.com/file/d/{name}/preview"
    
    def get_download_url(self, name):
        """
        Get direct download URL for a file.
        
        Args:
            name: The Google Drive file ID
        
        Returns:
            URL string for downloading
        """
        if not name:
            return None
        return f"https://drive.google.com/uc?export=download&id={name}"
    
    def size(self, name):
        """
        Get file size.
        
        Args:
            name: The Google Drive file ID
        
        Returns:
            File size in bytes
        """
        try:
            file_info = self.drive_service.drive_service.files().get(
                fileId=name,
                fields='size',
                supportsAllDrives=True
            ).execute()
            return int(file_info.get('size', 0))
        except Exception:
            return 0
    
    def _get_mime_type(self, extension):
        """Get MIME type from file extension"""
        mime_map = {
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.txt': 'text/plain',
        }
        return mime_map.get(extension.lower(), 'application/octet-stream')
    
    def get_valid_name(self, name):
        """Return a valid name for the file"""
        return name
    
    def get_available_name(self, name, max_length=None):
        """Return an available name (always unique due to UUID)"""
        return name


# Convenience function to get storage instance
def get_registration_document_storage():
    """Get the Google Drive storage instance for registration documents"""
    return GoogleDriveStorage()
