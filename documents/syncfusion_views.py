"""
Syncfusion Document Editor API endpoints for document operations
Handles loading documents from Cloudinary and saving back to Cloudinary
"""

from django.http import JsonResponse, HttpResponseBadRequest
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
import tempfile
from openpyxl import load_workbook
from django.conf import settings



@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def import_document(request):
    """
    Load a Word or Excel file from Cloudinary for editing.
    DOCX → convert to SFDT
    XLSX/XLS/CSV → return Cloudinary URL directly
    """
    try:
        data = json.loads(request.body)
        document_id = data.get("documentId")

        if not document_id:
            return JsonResponse({"error": "Document ID is required"}, status=400)

        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return JsonResponse({"error": "Document not found"}, status=404)

        if not document.can_open_in_editor(request.user):
            return JsonResponse(
                {"error": "You do not have permission to view this document"},
                status=403,
            )

        can_edit = document.can_edit(request.user)
        is_public = document.is_in_public_folder()

        file_url = document.file.url
        filename = document.title
        extension = os.path.splitext(filename)[1].lower()

        # ✅ If spreadsheet → skip SFDT conversion & return Cloudinary file
        if extension in [".xlsx", ".xls", ".csv"]:
            return JsonResponse(
                {
                    "type": "spreadsheet",
                    "fileUrl": file_url,
                    "fileName": filename,
                    "fileExtension": extension.replace(".", ""),
                    "documentId": document.id,
                    "canEdit": can_edit,
                    "isPublic": is_public,
                }
            )

        # ======================
        # ✅ DOCX logic continues
        # ======================
        response = requests.get(file_url)
        if response.status_code != 200:
            return JsonResponse(
                {"error": "Failed to download document from storage"}, status=500
            )

        file_content = response.content

        files = {
            "files": (
                filename,
                BytesIO(file_content),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }

        conversion_urls = [
            "https://services.syncfusion.com/react/production/api/documenteditor/Import",
            "https://ej2services.syncfusion.com/production/web-services/api/documenteditor/Import",
        ]

        sfdt_data = None
        last_error = None

        for url in conversion_urls:
            try:
                r = requests.post(url, files=files, timeout=30)
                if r.status_code == 200:
                    sfdt_data = r.text
                    break
                else:
                    last_error = f"{r.status_code}: {r.text}"
            except Exception as e:
                last_error = str(e)

        if not sfdt_data:
            return JsonResponse(
                {"error": f"SFDT conversion failed: {last_error}"}, status=500
            )

        return JsonResponse(
            {
                "type": "document",
                "sfdt": sfdt_data,
                "fileName": filename,
                "documentId": document.id,
                "canEdit": can_edit,
                "isPublic": is_public,
            }
        )

    except Exception as e:
        return JsonResponse({"error": f"Error loading document: {str(e)}"}, status=500)


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def export_document(request):
    """
    Save document back to Cloudinary
    Expects: { "documentId": <id>, "content": <base64_encoded_data>, "fileName": <name> }
    """
    try:
        data = json.loads(request.body)
        document_id = data.get("documentId")
        content = data.get("content")
        file_name = data.get("fileName")

        if not all([document_id, content]):
            return JsonResponse(
                {"error": "Document ID and content are required"}, status=400
            )

        # Get the document from database
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return JsonResponse({"error": "Document not found"}, status=404)

        # Check if user has permission to edit (save changes to original)
        if not document.can_edit(request.user):
            # If it's a public document, suggest making a copy
            if document.is_in_public_folder():
                return JsonResponse(
                    {
                        "error": "Cannot save changes to public documents",
                        "message": "This is a public document. Please make a copy to save your changes.",
                        "isPublic": True,
                    },
                    status=403,
                )
            else:
                return JsonResponse(
                    {
                        "error": "You do not have permission to edit this document",
                        "message": "Only the document owner or admin can save changes to this file.",
                    },
                    status=403,
                )

        # Decode base64 content
        file_content = base64.b64decode(content)

        # Get the old file information
        old_file_name = document.file.name
        file_extension = os.path.splitext(document.title)[1] or ".docx"

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
                cloudinary.uploader.destroy(
                    public_id, resource_type="raw", invalidate=True
                )
            except Exception as e:
                print(f"Error deleting old file: {e}")

        # Save the new file (this will upload to Cloudinary via the storage backend)
        document.file.save(file_name, file_obj, save=False)

        # Update document title if needed
        if file_name and file_name != document.title:
            document.title = file_name

        # Save the document model
        document.save()

        return JsonResponse(
            {
                "success": True,
                "message": "Document saved successfully",
                "documentId": document.id,
                "fileUrl": document.file.url,
            }
        )

    except Exception as e:
        return JsonResponse({"error": f"Error saving document: {str(e)}"}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def systemClipboard(request):
    """
    Handle system clipboard operations for Syncfusion
    This is required by Syncfusion Document Editor
    """
    try:
        data = json.loads(request.body)
        content = data.get("content", "")

        return JsonResponse({"content": content})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def restrictediting(request):
    """
    Handle restricted editing requests from Syncfusion
    """
    try:
        # For now, return empty response
        # You can implement user-specific editing restrictions here
        return JsonResponse({"canEdit": True})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


SYNCFUSION_OPEN_URL = "https://document.syncfusion.com/web-services/spreadsheet-editor/api/spreadsheet/open"

@csrf_exempt
@require_http_methods(["POST"])
def spreadsheet_open(request):
    file = request.FILES.get("file")
    if not file:
        return HttpResponseBadRequest("Missing file")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        for chunk in file.chunks():
            tmp.write(chunk)
        tmp.flush()

        files = {"file": open(tmp.name, "rb")}

        r = requests.post(SYNCFUSION_OPEN_URL, files=files)
        if r.status_code != 200:
            return JsonResponse({"error": "Syncfusion failed"}, status=500)

        # r.json() already returns workbook JSON
        return JsonResponse(r.json())

@csrf_exempt
@require_http_methods(["POST"])
def spreadsheet_save(request):

    data_base64 = request.POST.get("content")
    file_name = request.POST.get("fileName", "document.xlsx")

    if not data_base64:
        return HttpResponseBadRequest("Missing content")

    # Decode base64
    file_data = base64.b64decode(data_base64)

    # Save temporary file before uploading
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(file_data)
        tmp.flush()

        result = cloudinary.uploader.upload(
            tmp.name, resource_type="raw"
        )  # Excel must be stored as raw

    return JsonResponse(
        {"status": "success", "fileName": file_name, "url": result["secure_url"]}
    )
