"""
Google Drive Views - Using OAuth tokens from frontend
The frontend handles Google Sign-In and passes tokens to these endpoints
"""

import os
import json
import logging
from io import BytesIO

from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
import requests

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

from .models import Document, Folder
from .folder_utils import get_user_personal_folder
from users.models import User
from django.conf import settings

logger = logging.getLogger(__name__)

# App folder name in Google Drive
APP_FOLDER_NAME = "Sports Management Documents"

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


def normalize_extension(ext):
    """Normalize file extension to lowercase without dot"""
    if not ext:
        return ""
    return ext.lstrip(".").lower()


def is_excel_file(ext):
    """Check if extension is Excel format"""
    return normalize_extension(ext) in ['xlsx', 'xls']


def is_word_file(ext):
    """Check if extension is Word format"""
    return normalize_extension(ext) in ['docx', 'doc']


def get_or_create_app_folder(drive_service):
    """
    Get or create the app folder in user's Google Drive.
    Returns the folder ID.
    """
    try:
        # Search for existing app folder
        query = f"name='{APP_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = drive_service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)',
            pageSize=1
        ).execute()
        
        files = results.get('files', [])
        if files:
            return files[0]['id']
        
        # Create new app folder
        folder_metadata = {
            'name': APP_FOLDER_NAME,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = drive_service.files().create(
            body=folder_metadata,
            fields='id'
        ).execute()
        
        logger.info(f"Created app folder in Google Drive: {folder['id']}")
        return folder['id']
    except Exception as e:
        logger.warning(f"Failed to get/create app folder: {e}")
        return None


def get_credentials_from_tokens(token_data):
    """Create Credentials object from token data"""
    return Credentials(
        token=token_data.get('access_token'),
        refresh_token=token_data.get('refresh_token'),
        token_uri='https://oauth2.googleapis.com/token',
        client_id=getattr(settings, 'GOOGLE_OAUTH2_CLIENT_ID', ''),
        client_secret=getattr(settings, 'GOOGLE_OAUTH2_CLIENT_SECRET', ''),
    )


def get_embed_url(file_id, file_type='doc', edit=True):
    """Get the embed/edit URL for a Google Doc or Sheet"""
    if file_type == 'sheet':
        base = 'https://docs.google.com/spreadsheets/d'
    else:
        base = 'https://docs.google.com/document/d'
    
    mode = 'edit' if edit else 'preview'
    return f"{base}/{file_id}/{mode}"


@api_view(['GET'])
@permission_classes([AllowAny])
def get_google_auth_url(request):
    """
    Get Google OAuth2 authorization URL for the frontend to use
    """
    from google_auth_oauthlib.flow import Flow
    
    redirect_uri = request.GET.get('redirect_uri', 'http://localhost:5173/google-callback')
    document_id = request.GET.get('document_id', '')
    
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_OAUTH2_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH2_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    
    scopes = [
        'https://www.googleapis.com/auth/drive.file',
        'https://www.googleapis.com/auth/documents',
        'https://www.googleapis.com/auth/spreadsheets',
    ]
    
    flow = Flow.from_client_config(client_config, scopes=scopes, redirect_uri=redirect_uri)
    
    # If user is authenticated, include the user_id in the state. Otherwise only include document_id
    state_data = {'document_id': document_id}
    if hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
        state_data['user_id'] = request.user.id
    state = json.dumps(state_data)
    
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        state=state
    )
    
    return Response({
        'authUrl': auth_url,
        'redirectUri': redirect_uri,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def exchange_google_token(request):
    """
    Exchange authorization code for access tokens
    Uses direct HTTP request instead of OAuth library to avoid scope mismatch errors
    """
    code = request.data.get('code')
    redirect_uri = request.data.get('redirect_uri')
    
    logger.info(f"Token exchange request - redirect_uri: {redirect_uri}")
    
    if not code or not redirect_uri:
        return Response(
            {'error': 'Code and redirect_uri are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Use direct HTTP request to exchange token - avoids scope mismatch errors
        # when Google returns additional scopes from One Tap login or previous sessions
        token_response = requests.post(
            'https://oauth2.googleapis.com/token',
            data={
                'code': code,
                'client_id': settings.GOOGLE_OAUTH2_CLIENT_ID,
                'client_secret': settings.GOOGLE_OAUTH2_CLIENT_SECRET,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code',
            }
        )
        
        if token_response.status_code == 200:
            token_data = token_response.json()
            logger.info("Token exchange successful")
            return Response({
                'success': True,
                'tokens': {
                    'access_token': token_data.get('access_token'),
                    'refresh_token': token_data.get('refresh_token'),
                    'expires_in': token_data.get('expires_in'),
                }
            })
        else:
            error_detail = token_response.json().get('error_description', token_response.text)
            logger.error(f"Token exchange failed: {error_detail}")
            raise Exception(error_detail)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Token exchange error: {error_msg}")
        
        # Handle scope change error - this happens when Google returns additional scopes
        # (e.g., from One Tap login or previous sessions)
        if 'Scope has changed' in error_msg:
            # Try direct token exchange using requests instead of the OAuth library
            try:
                import requests as http_requests
                token_response = http_requests.post(
                    'https://oauth2.googleapis.com/token',
                    data={
                        'code': code,
                        'client_id': settings.GOOGLE_OAUTH2_CLIENT_ID,
                        'client_secret': settings.GOOGLE_OAUTH2_CLIENT_SECRET,
                        'redirect_uri': redirect_uri,
                        'grant_type': 'authorization_code',
                    }
                )
                
                if token_response.status_code == 200:
                    token_data = token_response.json()
                    logger.info("Token exchange successful (direct method)")
                    return Response({
                        'success': True,
                        'tokens': {
                            'access_token': token_data.get('access_token'),
                            'refresh_token': token_data.get('refresh_token'),
                            'expires_in': token_data.get('expires_in'),
                        }
                    })
                else:
                    error_detail = token_response.json().get('error_description', token_response.text)
                    logger.error(f"Direct token exchange failed: {error_detail}")
                    return Response(
                        {'error': f'Token exchange failed: {error_detail}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as direct_error:
                logger.error(f"Direct token exchange error: {direct_error}")
                return Response(
                    {'error': str(direct_error)},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        
        # Provide more helpful error messages
        if 'invalid_grant' in error_msg:
            return Response(
                {'error': 'Authorization code expired or already used. Please try signing in again.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return Response(
            {'error': error_msg},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_document_in_google_drive(request):
    """
    Create a new document directly in Google Drive (primary storage)
    This is the main upload endpoint for new documents
    """
    try:
        file = request.FILES.get('file')
        title = request.data.get('title')
        folder_id = request.data.get('folder')
        description = request.data.get('description', '')
        
        # Normalize token_data into a dict
        token_data = request.data.get('tokens')
        if token_data is None:
            token_data = {}
        elif isinstance(token_data, (bytes, str)):
            raw_token = str(token_data)
            try:
                token_data = json.loads(raw_token)
                if not isinstance(token_data, dict):
                    token_data = {}
            except Exception as e:
                logger.warning(f"Failed to JSON parse tokens (first 100 chars): {raw_token[:100]}")
                token_data = {}
        elif not isinstance(token_data, dict):
            logger.warning(f"Token payload unexpected type: {type(token_data)}")
            token_data = {}
        
        if not file:
            return Response({'error': 'File is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not title:
            return Response({'error': 'Title is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not token_data.get('access_token'):
            return Response({'error': 'Google authentication required', 'needsAuth': True}, status=status.HTTP_401_UNAUTHORIZED)
        
        # Get folder and validate permissions
        folder = None
        if folder_id:
            try:
                folder = Folder.objects.get(id=folder_id)
                if not folder.can_edit(request.user):
                    return Response(
                        {'error': 'You do not have permission to upload to this folder'},
                        status=status.HTTP_403_FORBIDDEN
                    )
            except Folder.DoesNotExist:
                return Response({'error': 'Folder not found'}, status=status.HTTP_404_NOT_FOUND)
        elif not request.user.is_admin:
            return Response({'error': 'Folder is required for non-admin users'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Check for duplicate title in folder
        if Document.objects.filter(title=title, folder=folder).exists():
            return Response(
                {'error': f"A file named '{title}' already exists in this folder"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get credentials
        credentials = get_credentials_from_tokens(token_data)
        drive_service = build('drive', 'v3', credentials=credentials)
        
        # Detect file type and MIME type (support broader set of files)
        _, ext = os.path.splitext(file.name)
        ext = ext.lower()
        convertible_doc = ext in ['.docx', '.doc']
        convertible_sheet = ext in ['.xlsx', '.xls']
        is_pdf = ext == '.pdf'
        is_image = ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.webp']
        is_text = ext in ['.txt', '.csv']
        is_ppt = ext in ['.ppt', '.pptx']

        # Base MIME types fallback
        mime_type_map = {
            '.docx': MIME_TYPES['docx'],
            '.doc': MIME_TYPES['doc'],
            '.xlsx': MIME_TYPES['xlsx'],
            '.xls': MIME_TYPES['xls'],
            '.pdf': MIME_TYPES['pdf'],
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.svg': 'image/svg+xml',
            '.webp': 'image/webp',
            '.txt': 'text/plain',
            '.csv': 'text/csv',
            '.ppt': 'application/vnd.ms-powerpoint',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        }

        mime_type = mime_type_map.get(ext, 'application/octet-stream')

        # Decide if we convert to Google Doc/Sheet or store as binary
        google_mime = None
        file_type = 'binary'
        if convertible_doc:
            google_mime = MIME_TYPES['google_doc']
            file_type = 'doc'
        elif convertible_sheet:
            google_mime = MIME_TYPES['google_sheet']
            file_type = 'sheet'

        # Get or create app folder in user's Google Drive
        app_folder_id = get_or_create_app_folder(drive_service)

        # Upload metadata
        file_metadata = {'name': title}
        if google_mime:
            file_metadata['mimeType'] = google_mime
        if app_folder_id:
            file_metadata['parents'] = [app_folder_id]
        
        media = MediaIoBaseUpload(
            BytesIO(file.read()),
            mimetype=mime_type,
            resumable=True
        )
        
        google_file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, mimeType, webViewLink, modifiedTime'
        ).execute()
        
        # Set permissions based on folder type
        is_public = folder and folder.folder_type == Folder.FolderType.PUBLIC
        
        if is_public:
            # Public folder: Anyone with link can EDIT (for admin access)
            try:
                drive_service.files().update(
                    fileId=google_file['id'],
                    body={'copyRequiresWriterPermission': False},
                    fields='id'
                ).execute()
                perm_result = drive_service.permissions().create(
                    fileId=google_file['id'],
                    body={
                        'type': 'anyone',
                        'role': 'writer',
                    },
                    fields='id'
                ).execute()
                logger.info(f"Set public write permissions for file {google_file['id']}, permission id: {perm_result.get('id')}")
                perms = drive_service.permissions().list(
                    fileId=google_file['id'],
                    fields='permissions(id,type,emailAddress,role)'
                ).execute()
                logger.info(f"Current permissions for file {google_file['id']}: {perms}")
            except Exception as perm_error:
                logger.error(f"Failed to set public edit permissions: {perm_error}")
        else:
            # Non-public folder: If uploader is NOT admin, share with all admins as writers
            if not request.user.is_admin:
                admin_users = User.objects.filter(role=User.Role.ADMIN)
                for admin in admin_users:
                    if admin.email:
                        try:
                            perm_result = drive_service.permissions().create(
                                fileId=google_file['id'],
                                body={
                                    'type': 'user',
                                    'role': 'writer',
                                    'emailAddress': admin.email,
                                },
                                sendNotificationEmail=False,
                                fields='id'
                            ).execute()
                            logger.info(f"Shared file {google_file['id']} with admin {admin.email}, permission id: {perm_result.get('id')}")
                        except Exception as share_error:
                            logger.warning(f"Failed to share with admin {admin.email}: {share_error}")
        
        # Create database record
        document = Document.objects.create(
            title=title,
            google_drive_id=google_file['id'],
            file_extension=ext,
            version=google_file.get('modifiedTime'),
            folder=folder,
            uploaded_by=request.user,
            owner=request.user,
            description=description,
        )
        
        # Build edit/view URL (only for convertible types)
        if file_type in ['doc', 'sheet']:
            edit_url = get_embed_url(google_file['id'], file_type, edit=True)
        else:
            # For non-convertible types, use webViewLink as fallback
            edit_url = google_file.get('webViewLink')
        
        return Response({
            'success': True,
            'document': {
                'id': document.id,
                'title': document.title,
                'googleFileId': google_file['id'],
                'editUrl': edit_url,
                'webViewLink': google_file.get('webViewLink'),
                'fileExtension': ext,
                'isPublic': is_public,
            }
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        error_str = str(e)
        logger.error(f"Document creation error: {e}")
        import traceback
        traceback.print_exc()
        
        # Check if it's a token expiration/revocation error
        if 'invalid_grant' in error_str or 'Token has been expired or revoked' in error_str:
            return Response(
                {
                    'error': 'Your Google authorization has expired. Please sign in with Google again.',
                    'code': 'TOKEN_EXPIRED'
                },
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        return Response(
            {'error': error_str},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_to_google_drive(request):
    """
    Upload a document to Google Drive for editing
    Requires Google OAuth tokens from the frontend
    """
    try:
        document_id = request.data.get('documentId')
        token_data = request.data.get('tokens')
        
        if not document_id:
            return Response(
                {'error': 'Document ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not token_data or not token_data.get('access_token'):
            return Response(
                {'error': 'Google authentication required', 'needsAuth': True},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Get document
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response(
                {'error': 'Document not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # If document has no folder (root-level), only allow owner/uploaded_by or admin
        if not document.folder:
            if not (getattr(request.user, 'is_admin', False) or document.owner == request.user or document.uploaded_by == request.user):
                return Response(
                    {'error': 'You do not have permission to view this document'},
                    status=status.HTTP_403_FORBIDDEN
                )
            logger.info(f"Opening root-level document {document.id} for {request.user.email}")

        # Check permissions
        if not document.can_open_in_editor(request.user):
            return Response(
                {'error': 'You do not have permission to view this document'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Determine if user can save changes back to original
        can_save = document.can_save_original(request.user)
        is_public = document.is_in_public_folder()
        
        # For public documents: anyone can edit in Google Docs
        # For private documents: only owner/admin can edit
        can_open_editor = is_public or can_save
        
        if not can_open_editor:
            return Response(
                {'error': 'You do not have permission to edit this document'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get credentials
        credentials = get_credentials_from_tokens(token_data)
        drive_service = build('drive', 'v3', credentials=credentials)
        
        # Check if already uploaded
        if document.google_drive_id:
            try:
                file_info = drive_service.files().get(
                    fileId=document.google_drive_id,
                    fields='id, name, mimeType, webViewLink'
                ).execute()
                
                file_type = 'sheet' if is_excel_file(document.file_extension) else 'doc'
                # Public docs open in view mode, owner/admin can edit
                edit_url = get_embed_url(document.google_drive_id, file_type, edit=can_save)
                
                return Response({
                    'googleFileId': document.google_drive_id,
                    'editUrl': edit_url,
                    'webViewLink': file_info.get('webViewLink'),
                    'canSave': can_save,  # Controls save button in frontend
                    'isPublic': is_public,
                    'fileName': document.title,
                })
            except Exception:
                document.google_drive_id = None
                document.save(update_fields=['google_drive_id'])
        
        # Download from Cloudinary
        file_url = document.cloudinary_url
        if not file_url:
            return Response(
                {'error': 'Document has no file to upload. The source file may be missing.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        response = requests.get(file_url, timeout=30)
        if response.status_code != 200:
            return Response(
                {'error': 'Failed to download document from storage'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Detect MIME type
        ext = normalize_extension(document.file_extension)
        if ext in ['xlsx', 'xls']:
            mime_type = MIME_TYPES['xlsx'] if ext == 'xlsx' else MIME_TYPES['xls']
            google_mime = MIME_TYPES['google_sheet']
            file_type = 'sheet'
        else:
            mime_type = MIME_TYPES['docx'] if ext == 'docx' else MIME_TYPES['doc']
            google_mime = MIME_TYPES['google_doc']
            file_type = 'doc'
        
        # Upload to Drive
        file_metadata = {
            'name': document.title,
            'mimeType': google_mime,
        }
        
        media = MediaIoBaseUpload(
            BytesIO(response.content),
            mimetype=mime_type,
            resumable=True
        )
        
        google_file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, mimeType, webViewLink'
        ).execute()
        
        # Set permissions for public files - view and copy allowed
        if is_public:
            try:
                # Allow copying by viewers
                drive_service.files().update(
                    fileId=google_file['id'],
                    body={'copyRequiresWriterPermission': False},
                    fields='id'
                ).execute()
                
                # Set permission for anyone with link to view
                drive_service.permissions().create(
                    fileId=google_file['id'],
                    body={
                        'type': 'anyone',
                        'role': 'reader',  # View only - cannot edit original
                    },
                    fields='id'
                ).execute()
            except Exception as perm_error:
                logger.warning(f"Failed to set public permissions: {perm_error}")
        
        # Save Google Drive ID
        document.google_drive_id = google_file['id']
        document.save(update_fields=['google_drive_id'])
        
        # Open in view mode for public, edit mode for owner/admin
        edit_url = get_embed_url(google_file['id'], file_type, edit=can_save)
        
        return Response({
            'googleFileId': google_file['id'],
            'editUrl': edit_url,
            'webViewLink': google_file.get('webViewLink'),
            'canSave': can_save,  # Controls save button in frontend
            'isPublic': is_public,
            'fileName': document.title,
        })
        
    except Exception as e:
        error_str = str(e)
        logger.error(f"Upload error: {e}")
        
        # Check if it's a token expiration/revocation error
        if 'invalid_grant' in error_str or 'Token has been expired or revoked' in error_str:
            return Response(
                {
                    'error': 'Your Google authorization has expired. Please sign in with Google again.',
                    'code': 'TOKEN_EXPIRED'
                },
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        return Response(
            {'error': error_str},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def sync_from_google_drive(request):
    """
    Download edited file from Google Drive and save back to Cloudinary
    """
    try:
        document_id = request.data.get('documentId')
        token_data = request.data.get('tokens')
        
        if not document_id:
            return Response({'error': 'Document ID is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not token_data or not token_data.get('access_token'):
            return Response({'error': 'Google authentication required', 'needsAuth': True}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response({'error': 'Document not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Only admin/owner can save changes back to the original
        if not document.can_save_original(request.user):
            return Response({'error': 'Only admins and the owner can save changes to the original file'}, status=status.HTTP_403_FORBIDDEN)
        
        if not document.google_drive_id:
            return Response({'error': 'Document is not linked to Google Drive'}, status=status.HTTP_400_BAD_REQUEST)
        
        credentials = get_credentials_from_tokens(token_data)
        drive_service = build('drive', 'v3', credentials=credentials)
        
        # Determine export format
        if is_excel_file(document.file_extension):
            export_mime = MIME_TYPES['xlsx']
            extension = '.xlsx'
        else:
            export_mime = MIME_TYPES['docx']
            extension = '.docx'
        
        # Export from Google Drive
        request_export = drive_service.files().export_media(
            fileId=document.google_drive_id,
            mimeType=export_mime
        )
        
        file_content = BytesIO()
        downloader = MediaIoBaseDownload(file_content, request_export)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        
        file_content.seek(0)
        content_bytes = file_content.read()
        
        # Save to Cloudinary
        import tempfile
        import cloudinary.uploader
        from cloudinary.utils import cloudinary_url
        
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as tmp_file:
            tmp_file.write(content_bytes)
            tmp_file_path = tmp_file.name
        
        try:
            upload_result = cloudinary.uploader.upload(
                tmp_file_path,
                public_id=document.file.name,
                resource_type='raw',
                overwrite=True,
                invalidate=True,
            )
            
            new_version = upload_result.get('version')
            file_url, _ = cloudinary_url(
                upload_result['public_id'],
                resource_type='raw',
                version=new_version,
            )
            
            document.version = str(new_version)
            document.save(update_fields=['version'])
            
            return Response({
                'success': True,
                'message': 'Document saved successfully',
                'documentId': document.id,
                'fileUrl': file_url,
                'version': new_version,
            })
        finally:
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)
                
    except Exception as e:
        error_str = str(e)
        logger.error(f"Sync error: {e}")
        
        # Check if it's a token expiration/revocation error
        if 'invalid_grant' in error_str or 'Token has been expired or revoked' in error_str:
            return Response(
                {
                    'error': 'Your Google authorization has expired. Please sign in with Google again.',
                    'code': 'TOKEN_EXPIRED'
                },
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        return Response({'error': error_str}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_google_drive_file(request):
    """Delete Google Drive copy of document"""
    try:
        document_id = request.data.get('documentId')
        token_data = request.data.get('tokens')
        
        if not document_id:
            return Response({'error': 'Document ID is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response({'error': 'Document not found'}, status=status.HTTP_404_NOT_FOUND)
        
        if document.google_drive_id and token_data and token_data.get('access_token'):
            try:
                credentials = get_credentials_from_tokens(token_data)
                drive_service = build('drive', 'v3', credentials=credentials)
                drive_service.files().delete(fileId=document.google_drive_id).execute()
            except Exception as e:
                logger.warning(f"Failed to delete Google Drive file: {e}")
            
            document.google_drive_id = None
            document.save(update_fields=['google_drive_id'])
        
        return Response({'success': True})
        
    except Exception as e:
        logger.error(f"Delete error: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_google_embed_url(request, document_id):
    """Get embed URL for document"""
    try:
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response({'error': 'Document not found'}, status=status.HTTP_404_NOT_FOUND)
        
        if not document.can_open_in_editor(request.user):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        can_edit = document.can_edit(request.user)
        
        if not document.google_drive_id:
            return Response({'error': 'Document not uploaded to Google Drive'}, status=status.HTTP_400_BAD_REQUEST)
        
        file_type = 'sheet' if is_excel_file(document.file_extension) else 'doc'
        # Always open in edit mode; save gated by canSave
        edit_url = get_embed_url(document.google_drive_id, file_type, edit=True)
        
        return Response({
            'editUrl': edit_url,
            'canSave': document.can_save_original(request.user),
            'isPublic': document.is_in_public_folder(),
            'fileName': document.title,
        })
        
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def download_from_google_drive(request, document_id):
    """
    Download a document from Google Drive
    Exports to original format (docx/xlsx)
    """
    try:
        token_data = request.GET.get('tokens')
        
        if not token_data:
            # Try from request body for POST
            token_data = request.data.get('tokens')
        
        if not token_data or not token_data.get('access_token'):
            return Response({'error': 'Google authentication required', 'needsAuth': True}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response({'error': 'Document not found'}, status=status.HTTP_404_NOT_FOUND)
        
        if not document.can_view(request.user):
            return Response(
                {'error': 'You do not have permission to view this document'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if not document.google_drive_id:
            return Response({'error': 'Document is not stored in Google Drive'}, status=status.HTTP_400_BAD_REQUEST)
        
        credentials = get_credentials_from_tokens(token_data)
        drive_service = build('drive', 'v3', credentials=credentials)
        
        # Determine export format
        if is_excel_file(document.file_extension):
            export_mime = MIME_TYPES['xlsx']
            extension = '.xlsx'
        else:
            export_mime = MIME_TYPES['docx']
            extension = '.docx'
        
        # Export from Google Drive
        request_export = drive_service.files().export_media(
            fileId=document.google_drive_id,
            mimeType=export_mime
        )
        
        file_content = BytesIO()
        downloader = MediaIoBaseDownload(file_content, request_export)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        
        file_content.seek(0)
        
        # Return file as download
        from django.http import HttpResponse
        response = HttpResponse(
            file_content.read(),
            content_type=export_mime
        )
        response['Content-Disposition'] = f'attachment; filename="{document.title}{extension}"'
        return response
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        import traceback
        traceback.print_exc()
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def open_document_in_google_drive(request):
    """
    Open a document directly in Google Drive (new tab)
    Returns the Google Drive edit URL for the document
    
    For documents stored in another user's Google Drive:
    - If current user is owner: use the existing file (they can edit)
    - If current user is admin/has edit permission: export and create a copy in their Drive
    - If current user is viewer only: return view-only URL
    """
    try:
        document_id = request.data.get('documentId')
        token_data = request.data.get('tokens')
        
        if not document_id:
            return Response(
                {'error': 'Document ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not token_data or not token_data.get('access_token'):
            return Response(
                {'error': 'Google authentication required', 'needsAuth': True},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Get document
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response(
                {'error': 'Document not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check permissions
        if not document.can_open_in_editor(request.user):
            return Response(
                {'error': 'You do not have permission to view this document'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Determine permissions
        can_save = document.can_save_original(request.user)
        is_public = document.is_in_public_folder()
        is_owner = document.owner == request.user or document.uploaded_by == request.user
        is_admin = request.user.is_admin if hasattr(request.user, 'is_admin') else False
        
        file_type = 'sheet' if is_excel_file(document.file_extension) else 'doc'
        
        # Get credentials for current user
        credentials = get_credentials_from_tokens(token_data)
        drive_service = build('drive', 'v3', credentials=credentials)
        
        # If document has a Google Drive ID
        if document.google_drive_id:
            # If user is the owner, they can access their own file directly
            if is_owner:
                edit_url = get_embed_url(document.google_drive_id, file_type, edit=True)
                return Response({
                    'googleFileId': document.google_drive_id,
                    'editUrl': edit_url,
                    'webViewLink': f"https://drive.google.com/file/d/{document.google_drive_id}/view",
                    'canSave': can_save,
                    'isPublic': is_public,
                    'fileName': document.title,
                })
            
            # For admin (not owner), they have been shared as writer on public files
            # So they can open and edit directly without creating a copy
            if is_admin:
                if is_public:
                    # Admin has writer access to public files (shared during upload)
                    edit_url = get_embed_url(document.google_drive_id, file_type, edit=True)
                    return Response({
                        'googleFileId': document.google_drive_id,
                        'editUrl': edit_url,
                        'webViewLink': f"https://drive.google.com/file/d/{document.google_drive_id}/view",
                        'canSave': True,  # Admin can save to original
                        'isPublic': is_public,
                        'fileName': document.title,
                    })
                else:
                    # Non-public file owned by someone else
                    # Admin can still try to open - they may have access through other means
                    edit_url = get_embed_url(document.google_drive_id, file_type, edit=True)
                    return Response({
                        'googleFileId': document.google_drive_id,
                        'editUrl': edit_url,
                        'webViewLink': f"https://drive.google.com/file/d/{document.google_drive_id}/view",
                        'canSave': True,
                        'isPublic': is_public,
                        'fileName': document.title,
                    })
            
            # For non-owners, check if they already have a copy of this document
            existing_copy = Document.objects.filter(
                original_document=document,
                owner=request.user,
                status=Document.DocumentStatus.COPY
            ).first()
            
            if existing_copy and existing_copy.google_drive_id:
                # User already has a copy, open it directly
                edit_url = get_embed_url(existing_copy.google_drive_id, file_type, edit=True)
                return Response({
                    'googleFileId': existing_copy.google_drive_id,
                    'editUrl': edit_url,
                    'webViewLink': f"https://drive.google.com/file/d/{existing_copy.google_drive_id}/view",
                    'canSave': True,  # User owns this copy
                    'isPublic': is_public,
                    'fileName': existing_copy.title,
                    'isCopy': True,
                    'copyId': existing_copy.id,
                })
            
            # For non-owners, we need to create a copy in their Drive and database
            try:
                # Determine file type and export format
                ext = normalize_extension(document.file_extension)
                if ext in ['xlsx', 'xls']:
                    export_mime = MIME_TYPES['xlsx']
                    google_mime = MIME_TYPES['google_sheet']
                else:
                    export_mime = MIME_TYPES['docx']
                    google_mime = MIME_TYPES['google_doc']
                
                # Try to download the file using the public export URL
                export_url = f"https://docs.google.com/{'spreadsheets' if file_type == 'sheet' else 'document'}/d/{document.google_drive_id}/export?format={'xlsx' if file_type == 'sheet' else 'docx'}"
                
                response = requests.get(export_url, timeout=30)
                
                if response.status_code == 200:
                    file_content = BytesIO(response.content)
                    
                    # Get or create app folder in user's Google Drive
                    app_folder_id = get_or_create_app_folder(drive_service)
                    
                    # Create unique copy name
                    base_title = document.title.rsplit('.', 1)[0] if '.' in document.title else document.title
                    copy_name = f"{base_title} (Copy)"
                    
                    # Upload to current user's Drive (in app folder)
                    file_metadata = {
                        'name': copy_name,
                        'mimeType': google_mime,
                    }
                    if app_folder_id:
                        file_metadata['parents'] = [app_folder_id]
                    
                    media = MediaIoBaseUpload(
                        file_content,
                        mimetype=export_mime,
                        resumable=True
                    )
                    
                    new_file = drive_service.files().create(
                        body=file_metadata,
                        media_body=media,
                        fields='id, name, mimeType, webViewLink'
                    ).execute()
                    
                    # Get user's personal folder for database copy
                    user_folder = get_user_personal_folder(request.user)
                    
                    # Create database record for the copy
                    copy_title_with_ext = f"{copy_name}{document.file_extension}"
                    
                    # Ensure unique title in the folder
                    existing_count = Document.objects.filter(
                        folder=user_folder,
                        title__startswith=copy_name
                    ).count()
                    if existing_count > 0:
                        copy_title_with_ext = f"{base_title} (Copy {existing_count + 1}){document.file_extension}"
                    
                    db_copy = Document.objects.create(
                        title=copy_title_with_ext,
                        google_drive_id=new_file['id'],
                        file_extension=document.file_extension,
                        folder=user_folder,
                        uploaded_by=request.user,
                        owner=request.user,
                        status=Document.DocumentStatus.COPY,
                        original_document=document,
                        description=f"Copy of {document.title} from Public folder",
                    )
                    
                    logger.info(f"Created document copy: {db_copy.id} with Google Drive ID: {new_file['id']}")
                    
                    # Return edit URL for the new copy
                    edit_url = get_embed_url(new_file['id'], file_type, edit=True)
                    
                    return Response({
                        'googleFileId': new_file['id'],
                        'editUrl': edit_url,
                        'webViewLink': new_file.get('webViewLink'),
                        'canSave': True,  # User owns this copy
                        'isPublic': is_public,
                        'fileName': db_copy.title,
                        'isCopy': True,
                        'copyId': db_copy.id,
                        'originalGoogleFileId': document.google_drive_id,
                    })
                else:
                    raise Exception(f"Export failed with status {response.status_code}")
                    
            except Exception as e:
                logger.warning(f"Failed to create copy via export: {e}")
                # Fall back to preview mode - at least they can view it in the browser
                edit_url = get_embed_url(document.google_drive_id, file_type, edit=False)
                return Response({
                    'googleFileId': document.google_drive_id,
                    'editUrl': edit_url,
                    'webViewLink': f"https://drive.google.com/file/d/{document.google_drive_id}/view",
                    'canSave': False,
                    'isPublic': is_public,
                    'fileName': document.title,
                    'warning': 'Opening in view-only mode. Full editing requires file owner access.',
                })
        
        # Document doesn't have a Google Drive ID yet
        # This means it's a legacy Cloudinary document that needs to be uploaded
        
        # Check if document has a Cloudinary URL
        file_url = document.cloudinary_url
        if not file_url:
            return Response(
                {'error': 'Document has no file to open. The file may have been deleted.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Download from Cloudinary
        response = requests.get(file_url, timeout=30)
        if response.status_code != 200:
            return Response(
                {'error': 'Failed to download document from storage'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        file_content = response.content
        
        # Detect MIME type
        ext = normalize_extension(document.file_extension)
        if ext in ['xlsx', 'xls']:
            mime_type = MIME_TYPES['xlsx'] if ext == 'xlsx' else MIME_TYPES['xls']
            google_mime = MIME_TYPES['google_sheet']
            file_type = 'sheet'
        else:
            mime_type = MIME_TYPES['docx'] if ext == 'docx' else MIME_TYPES['doc']
            google_mime = MIME_TYPES['google_doc']
            file_type = 'doc'
        
        # Get or create app folder in user's Google Drive
        app_folder_id = get_or_create_app_folder(drive_service)
        
        # Upload to Drive (in app folder)
        file_metadata = {
            'name': document.title,
            'mimeType': google_mime,
        }
        if app_folder_id:
            file_metadata['parents'] = [app_folder_id]
        
        media = MediaIoBaseUpload(
            BytesIO(file_content),
            mimetype=mime_type,
            resumable=True
        )
        
        google_file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, mimeType, webViewLink'
        ).execute()
        
        # Set permissions for public files - anyone with link can edit
        if is_public:
            try:
                # Allow copying by viewers
                drive_service.files().update(
                    fileId=google_file['id'],
                    body={'copyRequiresWriterPermission': False},
                    fields='id'
                ).execute()
                
                # Set permission for anyone with link to EDIT
                drive_service.permissions().create(
                    fileId=google_file['id'],
                    body={
                        'type': 'anyone',
                        'role': 'writer',  # Anyone with link can edit
                    },
                    fields='id'
                ).execute()
                logger.info(f"Set public write permissions for file {google_file['id']}")
            except Exception as perm_error:
                logger.warning(f"Failed to set public permissions: {perm_error}")
        
        # Save Google Drive ID
        document.google_drive_id = google_file['id']
        document.save(update_fields=['google_drive_id'])
        
        # Open in edit mode for owner/admin, view mode for public
        edit_url = get_embed_url(google_file['id'], file_type, edit=can_save)
        
        return Response({
            'googleFileId': google_file['id'],
            'editUrl': edit_url,
            'webViewLink': google_file.get('webViewLink'),
            'canSave': can_save,
            'isPublic': is_public,
            'fileName': document.title,
        })
        
    except Exception as e:
        logger.error(f"Open document error: {e}")
        import traceback
        traceback.print_exc()
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

