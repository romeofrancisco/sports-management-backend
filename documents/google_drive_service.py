"""
Google Drive API Service
Handles file upload, conversion, and management with Google Drive
"""

import os
import json
import tempfile
from io import BytesIO
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload, MediaIoBaseDownload
from django.conf import settings


class GoogleDriveService:
    """Service class for Google Drive operations"""
    
    # Scopes required for Drive, Docs, and Sheets access
    SCOPES = [
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/documents',
        'https://www.googleapis.com/auth/spreadsheets',
    ]
    
    # Default shared folder ID - service account must have access to this folder
    DEFAULT_FOLDER_ID = '1N5jGcUFeqc3zb5IVYdtJczUEbFulIYrb'
    
    # MIME type mappings
    MIME_TYPES = {
        'google_doc': 'application/vnd.google-apps.document',
        'google_sheet': 'application/vnd.google-apps.spreadsheet',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'doc': 'application/msword',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'xls': 'application/vnd.ms-excel',
        'pdf': 'application/pdf',
    }
    
    def __init__(self):
        """Initialize the Google Drive service with service account credentials"""
        self.credentials = None
        self.drive_service = None
        self.docs_service = None
        self.sheets_service = None
        self._initialize_services()
    
    def _initialize_services(self):
        """Initialize Google API services using service account"""
        try:
            # Path to service account JSON file
            service_account_path = os.path.join(
                settings.BASE_DIR, 'google-service-account.json'
            )
            
            # Check if file exists
            if not os.path.exists(service_account_path):
                # Try environment variable
                service_account_info = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
                if service_account_info:
                    credentials_info = json.loads(service_account_info)
                    self.credentials = service_account.Credentials.from_service_account_info(
                        credentials_info, scopes=self.SCOPES
                    )
                else:
                    raise FileNotFoundError(
                        "Google service account credentials not found. "
                        "Please create google-service-account.json or set GOOGLE_SERVICE_ACCOUNT_JSON env var."
                    )
            else:
                self.credentials = service_account.Credentials.from_service_account_file(
                    service_account_path, scopes=self.SCOPES
                )
            
            # Build services
            self.drive_service = build('drive', 'v3', credentials=self.credentials)
            self.docs_service = build('docs', 'v1', credentials=self.credentials)
            self.sheets_service = build('sheets', 'v4', credentials=self.credentials)
            
        except Exception as e:
            print(f"Error initializing Google services: {e}")
            raise
    
    def upload_file(self, file_content, filename, mime_type=None, convert_to_google=True, folder_id=None):
        """
        Upload a file to Google Drive
        
        Args:
            file_content: File content as bytes or file-like object
            filename: Name of the file
            mime_type: MIME type of the file (auto-detected if not provided)
            convert_to_google: If True, converts to Google Docs/Sheets format
            folder_id: Optional Google Drive folder ID (uses DEFAULT_FOLDER_ID if not provided)
        
        Returns:
            dict with file info (id, name, mimeType, webViewLink)
        """
        # Detect MIME type from extension if not provided
        if not mime_type:
            ext = os.path.splitext(filename)[1].lower()
            mime_type = self._get_mime_type(ext)
        
        # Use default folder if not specified
        if not folder_id:
            folder_id = self.DEFAULT_FOLDER_ID
        
        # Prepare file metadata
        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        
        # Determine if we should convert to Google format
        if convert_to_google:
            if mime_type in [self.MIME_TYPES['docx'], self.MIME_TYPES['doc']]:
                file_metadata['mimeType'] = self.MIME_TYPES['google_doc']
            elif mime_type in [self.MIME_TYPES['xlsx'], self.MIME_TYPES['xls']]:
                file_metadata['mimeType'] = self.MIME_TYPES['google_sheet']
        
        # Create media upload
        if isinstance(file_content, bytes):
            media = MediaIoBaseUpload(
                BytesIO(file_content),
                mimetype=mime_type,
                resumable=True
            )
        else:
            # file_content is a file-like object
            media = MediaIoBaseUpload(
                file_content,
                mimetype=mime_type,
                resumable=True
            )
        
        # Upload file - use supportsAllDrives for shared drive support
        file = self.drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, mimeType, webViewLink, webContentLink',
            supportsAllDrives=True
        ).execute()
        
        return file
    
    def upload_from_url(self, url, filename, convert_to_google=True, folder_id=None):
        """
        Download a file from URL and upload to Google Drive
        
        Args:
            url: URL to download file from
            filename: Name for the file
            convert_to_google: If True, converts to Google Docs/Sheets format
            folder_id: Optional Google Drive folder ID
        
        Returns:
            dict with file info
        """
        import requests
        
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        ext = os.path.splitext(filename)[1].lower()
        mime_type = self._get_mime_type(ext)
        
        return self.upload_file(
            file_content=response.content,
            filename=filename,
            mime_type=mime_type,
            convert_to_google=convert_to_google,
            folder_id=folder_id
        )
    
    def get_file(self, file_id):
        """
        Get file metadata from Google Drive
        
        Args:
            file_id: Google Drive file ID
        
        Returns:
            dict with file metadata
        """
        return self.drive_service.files().get(
            fileId=file_id,
            fields='id, name, mimeType, webViewLink, webContentLink, modifiedTime'
        ).execute()
    
    def download_file(self, file_id, export_mime_type=None):
        """
        Download a file from Google Drive
        
        Args:
            file_id: Google Drive file ID
            export_mime_type: MIME type to export as (for Google Docs/Sheets)
        
        Returns:
            File content as bytes
        """
        file_info = self.get_file(file_id)
        mime_type = file_info.get('mimeType', '')
        
        # If it's a Google Docs/Sheets file, we need to export it
        if mime_type.startswith('application/vnd.google-apps'):
            if not export_mime_type:
                # Default export formats
                if mime_type == self.MIME_TYPES['google_doc']:
                    export_mime_type = self.MIME_TYPES['docx']
                elif mime_type == self.MIME_TYPES['google_sheet']:
                    export_mime_type = self.MIME_TYPES['xlsx']
                else:
                    export_mime_type = self.MIME_TYPES['pdf']
            
            request = self.drive_service.files().export_media(
                fileId=file_id,
                mimeType=export_mime_type
            )
        else:
            request = self.drive_service.files().get_media(fileId=file_id)
        
        file_content = BytesIO()
        downloader = MediaIoBaseDownload(file_content, request)
        
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        file_content.seek(0)
        return file_content.read()
    
    def delete_file(self, file_id):
        """
        Delete a file from Google Drive
        
        Args:
            file_id: Google Drive file ID
        """
        self.drive_service.files().delete(fileId=file_id).execute()
    
    def share_file(self, file_id, email=None, role='reader', anyone=False):
        """
        Share a file with a user or make it publicly accessible
        
        Args:
            file_id: Google Drive file ID
            email: Email of the user to share with
            role: Permission role ('reader', 'writer', 'commenter')
            anyone: If True, makes the file accessible to anyone with the link
        
        Returns:
            Permission info
        """
        if anyone:
            permission = {
                'type': 'anyone',
                'role': role,
            }
        else:
            permission = {
                'type': 'user',
                'role': role,
                'emailAddress': email,
            }
        
        return self.drive_service.permissions().create(
            fileId=file_id,
            body=permission,
            fields='id'
        ).execute()
    
    def create_folder(self, name, parent_id=None):
        """
        Create a folder in Google Drive
        
        Args:
            name: Folder name
            parent_id: Optional parent folder ID
        
        Returns:
            dict with folder info
        """
        file_metadata = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        
        if parent_id:
            file_metadata['parents'] = [parent_id]
        
        return self.drive_service.files().create(
            body=file_metadata,
            fields='id, name, webViewLink'
        ).execute()
    
    def _get_mime_type(self, extension):
        """Get MIME type from file extension"""
        mime_map = {
            '.docx': self.MIME_TYPES['docx'],
            '.doc': self.MIME_TYPES['doc'],
            '.xlsx': self.MIME_TYPES['xlsx'],
            '.xls': self.MIME_TYPES['xls'],
            '.pdf': self.MIME_TYPES['pdf'],
        }
        return mime_map.get(extension, 'application/octet-stream')
    
    def get_embed_url(self, file_id, file_type='doc', edit=True):
        """
        Get the embed URL for a Google Doc or Sheet
        
        Args:
            file_id: Google Drive file ID
            file_type: 'doc' or 'sheet'
            edit: If True, returns edit URL; otherwise preview URL
        
        Returns:
            Embed URL string
        """
        if file_type == 'doc':
            base = 'https://docs.google.com/document/d'
        else:
            base = 'https://docs.google.com/spreadsheets/d'
        
        mode = 'edit' if edit else 'preview'
        return f"{base}/{file_id}/{mode}?embedded=true"
    
    def list_all_files(self):
        """
        List all files in Google Drive owned by the service account
        
        Returns:
            List of file dictionaries
        """
        files = []
        page_token = None
        
        while True:
            response = self.drive_service.files().list(
                pageSize=100,
                fields="nextPageToken, files(id, name, mimeType, size, createdTime)",
                pageToken=page_token
            ).execute()
            
            files.extend(response.get('files', []))
            page_token = response.get('nextPageToken')
            
            if not page_token:
                break
        
        return files
    
    def delete_all_files(self):
        """
        Delete all files in Google Drive owned by the service account
        Use with caution!
        
        Returns:
            Number of files deleted
        """
        files = self.list_all_files()
        deleted_count = 0
        
        for file in files:
            try:
                self.delete_file(file['id'])
                deleted_count += 1
                print(f"Deleted: {file['name']} ({file['id']})")
            except Exception as e:
                print(f"Failed to delete {file['name']}: {e}")
        
        return deleted_count
    
    def get_storage_quota(self):
        """
        Get storage quota information
        
        Returns:
            dict with limit, usage, usageInDrive, usageInDriveTrash
        """
        about = self.drive_service.about().get(fields="storageQuota").execute()
        return about.get('storageQuota', {})


# Singleton instance
_drive_service = None

def get_drive_service():
    """Get or create the Google Drive service singleton"""
    global _drive_service
    if _drive_service is None:
        _drive_service = GoogleDriveService()
    return _drive_service
