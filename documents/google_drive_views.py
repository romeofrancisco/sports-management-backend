"""
Google Drive API Views
Handles document operations with Google Drive for editing in Google Docs/Sheets
"""

import os
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
import requests

from .models import Document
from .google_drive_service import get_drive_service


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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_to_google_drive(request):
    """
    Upload a document from Cloudinary to Google Drive for editing
    Converts the file to Google Docs/Sheets format
    
    Expects: { "documentId": <id> }
    Returns: { "googleFileId": <id>, "embedUrl": <url>, "webViewLink": <url> }
    """
    try:
        data = request.data
        document_id = data.get('documentId')
        
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
        
        # Check permissions
        if not document.can_open_in_editor(request.user):
            return Response(
                {'error': 'You do not have permission to view this document'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        can_edit = document.can_edit(request.user)
        is_public = document.is_in_public_folder()
        
        # Check if document already has a Google Drive ID
        if document.google_drive_id:
            try:
                drive_service = get_drive_service()
                file_info = drive_service.get_file(document.google_drive_id)
                
                # Determine file type for embed URL
                file_type = 'sheet' if is_excel_file(document.file_extension) else 'doc'
                embed_url = drive_service.get_embed_url(
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
            except Exception:
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
        drive_service = get_drive_service()
        google_file = drive_service.upload_file(
            file_content=response.content,
            filename=document.title,
            convert_to_google=True
        )
        
        # Make file accessible
        drive_service.share_file(google_file['id'], anyone=True, role='writer' if can_edit else 'reader')
        
        # Save Google Drive ID to document
        document.google_drive_id = google_file['id']
        document.save(update_fields=['google_drive_id'])
        
        # Determine file type for embed URL
        file_type = 'sheet' if is_excel_file(document.file_extension) else 'doc'
        embed_url = drive_service.get_embed_url(
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
        return Response(
            {'error': f'Error uploading to Google Drive: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def sync_from_google_drive(request):
    """
    Download the edited file from Google Drive and save back to Cloudinary
    
    Expects: { "documentId": <id> }
    Returns: { "success": true, "fileUrl": <url> }
    """
    try:
        data = request.data
        document_id = data.get('documentId')
        
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
        
        # Download from Google Drive
        drive_service = get_drive_service()
        
        # Determine export format based on file extension
        if is_excel_file(document.file_extension):
            export_mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            extension = '.xlsx'
        else:
            export_mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            extension = '.docx'
        
        file_content = drive_service.download_file(
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
        return Response(
            {'error': f'Error syncing from Google Drive: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_google_drive_file(request):
    """
    Delete the Google Drive copy of a document
    Called when closing the editor or when document is deleted
    
    Expects: { "documentId": <id> }
    """
    try:
        data = request.data
        document_id = data.get('documentId')
        
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
        if document.google_drive_id:
            try:
                drive_service = get_drive_service()
                drive_service.delete_file(document.google_drive_id)
            except Exception as e:
                print(f"Error deleting Google Drive file: {e}")
            
            # Clear the Google Drive ID
            document.google_drive_id = None
            document.save(update_fields=['google_drive_id'])
        
        return Response({'success': True})
        
    except Exception as e:
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
        
        drive_service = get_drive_service()
        file_type = 'sheet' if is_excel_file(document.file_extension) else 'doc'
        embed_url = drive_service.get_embed_url(
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
        return Response(
            {'error': f'Error getting embed URL: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
