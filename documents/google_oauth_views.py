"""
Google OAuth2 Views
Handles OAuth2 flow and document operations with Google Drive
"""

import json
import os
import logging
from urllib.parse import urlencode

from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
import requests

from .models import Document
from . import google_oauth_service as google_service

logger = logging.getLogger(__name__)


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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_auth_url(request):
    """
    Get Google OAuth2 authorization URL
    
    Query params:
        - redirect_uri: Where to redirect after auth
        - document_id: (optional) Document ID to open after auth
    
    Returns: { "authUrl": <url> }
    """
    frontend_url = request.GET.get('redirect_uri', '')
    document_id = request.GET.get('document_id', '')
    
    # Build redirect URI (frontend will handle the callback)
    redirect_uri = f"{frontend_url}/google-callback"
    
    # State contains document_id and user info for security
    state_data = {
        'document_id': document_id,
        'user_id': request.user.id,
    }
    state = json.dumps(state_data)
    
    auth_url, _ = google_service.get_authorization_url(redirect_uri, state=state)
    
    return Response({
        'authUrl': auth_url,
        'redirectUri': redirect_uri,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def exchange_token(request):
    """
    Exchange authorization code for access tokens
    
    Expects: { "code": <auth_code>, "redirect_uri": <uri> }
    Returns: { "access_token": <token>, "refresh_token": <token>, ... }
    """
    try:
        code = request.data.get('code')
        redirect_uri = request.data.get('redirect_uri')
        
        if not code:
            return Response(
                {'error': 'Authorization code is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not redirect_uri:
            return Response(
                {'error': 'Redirect URI is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Exchange code for tokens
        tokens = google_service.exchange_code_for_tokens(code, redirect_uri)
        
        return Response({
            'success': True,
            'tokens': tokens,
        })
        
    except Exception as e:
        logger.error(f"Error exchanging token: {e}")
        return Response(
            {'error': f'Failed to exchange token: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_to_google_drive(request):
    """
    Upload a document from Cloudinary to user's Google Drive for editing
    
    Expects: { 
        "documentId": <id>,
        "tokens": { "access_token": ..., "refresh_token": ... }
    }
    Returns: { "googleFileId": <id>, "embedUrl": <url>, "webViewLink": <url> }
    """
    try:
        data = request.data
        document_id = data.get('documentId')
        token_data = data.get('tokens')
        
        if not document_id:
            return Response(
                {'error': 'Document ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not token_data or not token_data.get('access_token'):
            return Response(
                {'error': 'Google tokens are required. Please sign in with Google first.'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Get document from database
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
        
        can_edit = document.can_edit(request.user)
        is_public = document.is_in_public_folder()
        
        # Get credentials from tokens
        credentials = google_service.get_credentials_from_tokens(token_data)
        
        # Check if document already has a Google Drive ID
        if document.google_drive_id:
            try:
                drive_service = google_service.get_drive_service(credentials)
                file_info = drive_service.files().get(
                    fileId=document.google_drive_id,
                    fields='id, name, mimeType, webViewLink'
                ).execute()
                
                # Determine file type for embed URL
                file_type = 'sheet' if is_excel_file(document.file_extension) else 'doc'
                embed_url = google_service.get_embed_url(
                    document.google_drive_id,
                    file_type=file_type,
                    edit=can_edit
                )
                
                return Response({
                    'googleFileId': document.google_drive_id,
                    'embedUrl': embed_url,
                    'webViewLink': file_info.get('webViewLink'),
                    'canEdit': can_edit,
                    'isPublic': is_public,
                    'fileName': document.title,
                })
            except Exception as e:
                logger.warning(f"Google Drive file not found, re-uploading: {e}")
                # File doesn't exist in Google Drive anymore, re-upload
                document.google_drive_id = None
                document.save(update_fields=['google_drive_id'])
        
        # Download file from Cloudinary
        file_url = document.file.url
        if document.version:
            file_url = f"{file_url}?v={document.version}"
        
        response = requests.get(file_url, timeout=30)
        if response.status_code != 200:
            return Response(
                {'error': 'Failed to download document from storage'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Upload to Google Drive
        google_file = google_service.upload_file_to_drive(
            credentials=credentials,
            file_content=response.content,
            filename=document.title,
            convert_to_google=True
        )
        
        # Share file (anyone with link can edit/view)
        google_service.share_file(
            credentials, 
            google_file['id'], 
            role='writer' if can_edit else 'reader'
        )
        
        # Save Google Drive ID to document
        document.google_drive_id = google_file['id']
        document.save(update_fields=['google_drive_id'])
        
        # Determine file type for embed URL
        file_type = 'sheet' if is_excel_file(document.file_extension) else 'doc'
        embed_url = google_service.get_embed_url(
            google_file['id'],
            file_type=file_type,
            edit=can_edit
        )
        
        return Response({
            'googleFileId': google_file['id'],
            'embedUrl': embed_url,
            'webViewLink': google_file.get('webViewLink'),
            'canEdit': can_edit,
            'isPublic': is_public,
            'fileName': document.title,
        })
        
    except Exception as e:
        logger.error(f"Error uploading to Google Drive: {e}")
        return Response(
            {'error': f'Error uploading to Google Drive: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def sync_from_google_drive(request):
    """
    Download the edited file from Google Drive and save back to Cloudinary
    
    Expects: { 
        "documentId": <id>,
        "tokens": { "access_token": ..., "refresh_token": ... }
    }
    Returns: { "success": true, "fileUrl": <url> }
    """
    try:
        data = request.data
        document_id = data.get('documentId')
        token_data = data.get('tokens')
        
        if not document_id:
            return Response(
                {'error': 'Document ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not token_data or not token_data.get('access_token'):
            return Response(
                {'error': 'Google tokens are required'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Get document from database
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response(
                {'error': 'Document not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check edit permissions
        if not document.can_edit(request.user):
            if document.is_in_public_folder():
                return Response(
                    {
                        'error': 'Cannot save changes to public documents',
                        'message': 'This is a public document. Please make a copy to save your changes.',
                        'isPublic': True,
                    },
                    status=status.HTTP_403_FORBIDDEN
                )
            return Response(
                {'error': 'You do not have permission to edit this document'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if document has a Google Drive ID
        if not document.google_drive_id:
            return Response(
                {'error': 'Document is not linked to Google Drive'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get credentials from tokens
        credentials = google_service.get_credentials_from_tokens(token_data)
        
        # Determine export format based on file extension
        if is_excel_file(document.file_extension):
            export_mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            extension = '.xlsx'
        else:
            export_mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            extension = '.docx'
        
        # Download from Google Drive
        file_content = google_service.download_file(
            credentials,
            document.google_drive_id,
            export_mime_type=export_mime
        )
        
        # Save to Cloudinary
        import tempfile
        import cloudinary.uploader
        from cloudinary.utils import cloudinary_url
        
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as tmp_file:
            tmp_file.write(file_content)
            tmp_file_path = tmp_file.name
        
        try:
            # Upload to Cloudinary (overwrite existing)
            upload_result = cloudinary.uploader.upload(
                tmp_file_path,
                public_id=document.file.name,
                resource_type='raw',
                overwrite=True,
                invalidate=True,
            )
            
            # Update document version
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
            # Clean up temp file
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)
        
    except Exception as e:
        logger.error(f"Error syncing from Google Drive: {e}")
        return Response(
            {'error': f'Error syncing from Google Drive: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_google_drive_file(request):
    """
    Delete the Google Drive copy of a document
    
    Expects: { 
        "documentId": <id>,
        "tokens": { "access_token": ..., "refresh_token": ... }
    }
    """
    try:
        data = request.data
        document_id = data.get('documentId')
        token_data = data.get('tokens')
        
        if not document_id:
            return Response(
                {'error': 'Document ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get document from database
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response(
                {'error': 'Document not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Delete from Google Drive if exists
        if document.google_drive_id and token_data and token_data.get('access_token'):
            try:
                credentials = google_service.get_credentials_from_tokens(token_data)
                google_service.delete_file(credentials, document.google_drive_id)
            except Exception as e:
                logger.warning(f"Error deleting Google Drive file: {e}")
            
            # Clear the Google Drive ID
            document.google_drive_id = None
            document.save(update_fields=['google_drive_id'])
        
        return Response({'success': True})
        
    except Exception as e:
        logger.error(f"Error deleting Google Drive file: {e}")
        return Response(
            {'error': f'Error deleting Google Drive file: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_google_embed_url(request, document_id):
    """
    Get the Google Docs/Sheets embed URL for a document
    
    Returns: { "embedUrl": <url>, "canEdit": <bool> }
    """
    try:
        # Get document from database
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
        
        can_edit = document.can_edit(request.user)
        
        if not document.google_drive_id:
            return Response(
                {'error': 'Document is not uploaded to Google Drive yet'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        file_type = 'sheet' if is_excel_file(document.file_extension) else 'doc'
        embed_url = google_service.get_embed_url(
            document.google_drive_id,
            file_type=file_type,
            edit=can_edit
        )
        
        return Response({
            'embedUrl': embed_url,
            'canEdit': can_edit,
            'isPublic': document.is_in_public_folder(),
            'fileName': document.title,
        })
        
    except Exception as e:
        logger.error(f"Error getting embed URL: {e}")
        return Response(
            {'error': f'Error getting embed URL: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
