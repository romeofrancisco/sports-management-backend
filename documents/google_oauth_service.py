"""
Google OAuth2 Service for Drive/Docs/Sheets
Uses user authentication instead of service account
"""

import os
import json
from io import BytesIO
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from django.conf import settings


# OAuth2 Scopes
# Using only drive.file scope (non-sensitive) - allows access to files created/opened by this app
# This avoids the "Google hasn't verified this app" warning for sensitive scopes
SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
]

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


def get_oauth_flow(redirect_uri):
    """Create OAuth2 flow for Google Sign-In"""
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_OAUTH2_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH2_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    
    return flow


def get_authorization_url(redirect_uri, state=None):
    """
    Generate Google OAuth2 authorization URL
    
    Args:
        redirect_uri: URL to redirect after auth
        state: Optional state parameter for security
    
    Returns:
        (authorization_url, state)
    """
    flow = get_oauth_flow(redirect_uri)
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='false',  # Don't include old scopes - use only current SCOPES
        prompt='consent',  # Always show consent screen to get new tokens with updated scopes
        state=state
    )
    
    return authorization_url, state


def exchange_code_for_tokens(code, redirect_uri):
    """
    Exchange authorization code for access/refresh tokens
    
    Args:
        code: Authorization code from OAuth callback
        redirect_uri: Must match the one used in authorization
    
    Returns:
        dict with access_token, refresh_token, expires_in, etc.
    """
    flow = get_oauth_flow(redirect_uri)
    flow.fetch_token(code=code)
    
    credentials = flow.credentials
    
    return {
        'access_token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'expires_in': credentials.expiry.isoformat() if credentials.expiry else None,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': list(credentials.scopes) if credentials.scopes else SCOPES,
    }


def get_credentials_from_tokens(token_data):
    """
    Create Credentials object from stored token data
    
    Args:
        token_data: dict with access_token, refresh_token, etc.
    
    Returns:
        google.oauth2.credentials.Credentials
    """
    return Credentials(
        token=token_data.get('access_token'),
        refresh_token=token_data.get('refresh_token'),
        token_uri='https://oauth2.googleapis.com/token',
        client_id=settings.GOOGLE_OAUTH2_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH2_CLIENT_SECRET,
        scopes=token_data.get('scopes', SCOPES)
    )


def get_drive_service(credentials):
    """Build Google Drive service from credentials"""
    return build('drive', 'v3', credentials=credentials)


def get_docs_service(credentials):
    """Build Google Docs service from credentials"""
    return build('docs', 'v1', credentials=credentials)


def get_sheets_service(credentials):
    """Build Google Sheets service from credentials"""
    return build('sheets', 'v4', credentials=credentials)


def upload_file_to_drive(credentials, file_content, filename, convert_to_google=True):
    """
    Upload a file to user's Google Drive
    
    Args:
        credentials: OAuth2 credentials
        file_content: File content as bytes
        filename: Name of the file
        convert_to_google: If True, converts to Google Docs/Sheets format
    
    Returns:
        dict with file info (id, name, mimeType, webViewLink)
    """
    drive_service = get_drive_service(credentials)
    
    # Detect MIME type from extension
    ext = os.path.splitext(filename)[1].lower()
    mime_type = _get_mime_type(ext)
    
    # Prepare file metadata
    file_metadata = {'name': filename}
    
    # Determine if we should convert to Google format
    if convert_to_google:
        if mime_type in [MIME_TYPES['docx'], MIME_TYPES['doc']]:
            file_metadata['mimeType'] = MIME_TYPES['google_doc']
        elif mime_type in [MIME_TYPES['xlsx'], MIME_TYPES['xls']]:
            file_metadata['mimeType'] = MIME_TYPES['google_sheet']
    
    # Create media upload
    media = MediaIoBaseUpload(
        BytesIO(file_content),
        mimetype=mime_type,
        resumable=True
    )
    
    # Upload file
    file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id, name, mimeType, webViewLink, webContentLink'
    ).execute()
    
    return file


def upload_from_url(credentials, url, filename, convert_to_google=True):
    """
    Download a file from URL and upload to user's Google Drive
    
    Args:
        credentials: OAuth2 credentials
        url: URL to download file from
        filename: Name for the file
        convert_to_google: If True, converts to Google Docs/Sheets format
    
    Returns:
        dict with file info
    """
    import requests
    
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    
    return upload_file_to_drive(
        credentials=credentials,
        file_content=response.content,
        filename=filename,
        convert_to_google=convert_to_google
    )


def download_file(credentials, file_id, export_mime_type=None):
    """
    Download a file from Google Drive
    
    Args:
        credentials: OAuth2 credentials
        file_id: Google Drive file ID
        export_mime_type: MIME type to export as (for Google Docs/Sheets)
    
    Returns:
        File content as bytes
    """
    drive_service = get_drive_service(credentials)
    
    # Get file info
    file_info = drive_service.files().get(
        fileId=file_id,
        fields='id, name, mimeType'
    ).execute()
    
    mime_type = file_info.get('mimeType', '')
    
    # If it's a Google Docs/Sheets file, we need to export it
    if mime_type.startswith('application/vnd.google-apps'):
        if not export_mime_type:
            # Default export formats
            if mime_type == MIME_TYPES['google_doc']:
                export_mime_type = MIME_TYPES['docx']
            elif mime_type == MIME_TYPES['google_sheet']:
                export_mime_type = MIME_TYPES['xlsx']
            else:
                export_mime_type = MIME_TYPES['pdf']
        
        request = drive_service.files().export_media(
            fileId=file_id,
            mimeType=export_mime_type
        )
    else:
        request = drive_service.files().get_media(fileId=file_id)
    
    file_content = BytesIO()
    downloader = MediaIoBaseDownload(file_content, request)
    
    done = False
    while not done:
        status, done = downloader.next_chunk()
    
    file_content.seek(0)
    return file_content.read()


def delete_file(credentials, file_id):
    """
    Delete a file from Google Drive
    
    Args:
        credentials: OAuth2 credentials
        file_id: Google Drive file ID
    """
    drive_service = get_drive_service(credentials)
    drive_service.files().delete(fileId=file_id).execute()


def share_file(credentials, file_id, role='writer', anyone=True):
    """
    Share a file - by default makes it accessible to anyone with link
    
    Args:
        credentials: OAuth2 credentials
        file_id: Google Drive file ID
        role: Permission role ('reader', 'writer', 'commenter')
        anyone: If True, makes the file accessible to anyone with the link
    
    Returns:
        Permission info
    """
    drive_service = get_drive_service(credentials)
    
    permission = {
        'type': 'anyone',
        'role': role,
    }
    
    return drive_service.permissions().create(
        fileId=file_id,
        body=permission,
        fields='id'
    ).execute()


def get_embed_url(file_id, file_type='doc', edit=True):
    """
    Get the embed URL for a Google Doc or Sheet
    
    Args:
        file_id: Google Drive file ID
        file_type: 'doc' or 'sheet'
        edit: If True, returns edit URL; otherwise preview URL
    
    Returns:
        Embed URL string
    """
    if file_type == 'sheet':
        base = 'https://docs.google.com/spreadsheets/d'
    else:
        base = 'https://docs.google.com/document/d'
    
    mode = 'edit' if edit else 'preview'
    return f"{base}/{file_id}/{mode}?embedded=true"


def _get_mime_type(extension):
    """Get MIME type from file extension"""
    mime_map = {
        '.docx': MIME_TYPES['docx'],
        '.doc': MIME_TYPES['doc'],
        '.xlsx': MIME_TYPES['xlsx'],
        '.xls': MIME_TYPES['xls'],
        '.pdf': MIME_TYPES['pdf'],
    }
    return mime_map.get(extension, 'application/octet-stream')
