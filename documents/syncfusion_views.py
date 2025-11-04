"""
Syncfusion Document Editor API endpoints for document operations
Handles loading documents from Cloudinary and saving back to Cloudinary
"""
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
import json
import base64
import requests
from io import BytesIO
from .models import Document
import cloudinary.uploader
import os
import subprocess
import tempfile


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_document(request):
    """
    Load a document from Cloudinary for editing in Syncfusion
    Returns the raw file for client-side processing
    Expects: { "documentId": <id> }
    Returns: Binary file download
    """
    try:
        data = json.loads(request.body)
        document_id = data.get('documentId')
        
        if not document_id:
            return JsonResponse({
                'error': 'Document ID is required'
            }, status=400)
        
        # Get the document from database
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return JsonResponse({
                'error': 'Document not found'
            }, status=404)
        
        # Check if user has permission to open in editor
        if not document.can_open_in_editor(request.user):
            return JsonResponse({
                'error': 'You do not have permission to view this document'
            }, status=403)
        
        # Check if user can edit (save changes to) this document
        can_edit = document.can_edit(request.user)
        is_public = document.is_in_public_folder()
        
        # Download document from Cloudinary
        file_url = document.file.url
        response = requests.get(file_url)
        
        if response.status_code != 200:
            return JsonResponse({
                'error': 'Failed to download document from storage'
            }, status=500)
        
        # Convert DOCX to SFDT using Syncfusion's web service
        file_content = response.content
        
        # Get file extension to determine format
        file_extension = os.path.splitext(document.title)[1].lower()
        
        # Prepare multipart form data with proper content type
        files = {
            'files': (
                document.title,
                BytesIO(file_content),
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
        }
        
        # Try different Syncfusion conversion endpoints
        conversion_urls = [
            'https://services.syncfusion.com/react/production/api/documenteditor/Import',
            'https://ej2services.syncfusion.com/production/web-services/api/documenteditor/Import'
        ]
        
        sfdt_data = None
        last_error = None
        
        for conversion_url in conversion_urls:
            try:
                conversion_response = requests.post(
                    conversion_url, 
                    files=files,
                    timeout=30
                )
                
                if conversion_response.status_code == 200:
                    sfdt_data = conversion_response.text
                    break
                else:
                    last_error = f"Status {conversion_response.status_code}: {conversion_response.text}"
            except Exception as e:
                last_error = str(e)
                continue
        
        if not sfdt_data:
            return JsonResponse({
                'error': f'Failed to convert document to SFDT format. Last error: {last_error}'
            }, status=500)
        
        # Return SFDT JSON with permission info
        return JsonResponse({
            'sfdt': sfdt_data,
            'fileName': document.title,
            'documentId': document.id,
            'canEdit': can_edit,
            'isPublic': is_public
        })
        
    except Exception as e:
        return JsonResponse({
            'error': f'Error loading document: {str(e)}'
        }, status=500)


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def export_document(request):
    """
    Save document back to Cloudinary
    Expects: { "documentId": <id>, "content": <base64_encoded_data>, "fileName": <name> }
    """
    try:
        data = json.loads(request.body)
        document_id = data.get('documentId')
        content = data.get('content')
        file_name = data.get('fileName')
        
        if not all([document_id, content]):
            return JsonResponse({
                'error': 'Document ID and content are required'
            }, status=400)
        
        # Get the document from database
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return JsonResponse({
                'error': 'Document not found'
            }, status=404)
        
        # Check if user has permission to edit (save changes to original)
        if not document.can_edit(request.user):
            # If it's a public document, suggest making a copy
            if document.is_in_public_folder():
                return JsonResponse({
                    'error': 'Cannot save changes to public documents',
                    'message': 'This is a public document. Please make a copy to save your changes.',
                    'isPublic': True
                }, status=403)
            else:
                return JsonResponse({
                    'error': 'You do not have permission to edit this document',
                    'message': 'Only the document owner or admin can save changes to this file.'
                }, status=403)
        
        # Decode base64 content
        file_content = base64.b64decode(content)
        
        # Get the old file information
        old_file_name = document.file.name
        file_extension = os.path.splitext(document.title)[1] or '.docx'
        
        # Ensure the filename has the correct extension
        if not file_name:
            file_name = document.title
        if not file_name.endswith(file_extension):
            file_name = f"{os.path.splitext(file_name)[0]}{file_extension}"
        
        # Create a temporary file-like object
        from django.core.files.base import ContentFile
        file_obj = ContentFile(file_content, name=file_name)
        
        # Delete old file from Cloudinary
        if document.file:
            try:
                # Extract public_id from the file name
                public_id = os.path.splitext(document.file.name)[0]
                cloudinary.uploader.destroy(public_id, resource_type="raw", invalidate=True)
            except Exception as e:
                print(f"Error deleting old file: {e}")
        
        # Save the new file (this will upload to Cloudinary via the storage backend)
        document.file.save(file_name, file_obj, save=False)
        
        # Update document title if needed
        if file_name and file_name != document.title:
            document.title = file_name
        
        # Save the document model
        document.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Document saved successfully',
            'documentId': document.id,
            'fileUrl': document.file.url
        })
        
    except Exception as e:
        return JsonResponse({
            'error': f'Error saving document: {str(e)}'
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def systemClipboard(request):
    """
    Handle system clipboard operations for Syncfusion
    This is required by Syncfusion Document Editor
    """
    try:
        data = json.loads(request.body)
        content = data.get('content', '')
        
        return JsonResponse({
            'content': content
        })
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def restrictediting(request):
    """
    Handle restricted editing requests from Syncfusion
    """
    try:
        # For now, return empty response
        # You can implement user-specific editing restrictions here
        return JsonResponse({
            'canEdit': True
        })
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)
