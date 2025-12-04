"""
Document Transfer Service
Handles syncing registration documents to the Documents app when player registration is approved.

NOTE: Service accounts don't have storage quota for Google Drive uploads.
Documents stay in Cloudinary initially. When the player wants to edit a document,
they authenticate with Google and the document is uploaded to their personal 
Google Drive at that time.
"""

import os
from .models import Document, Folder


def sync_registration_document_to_documents_app(reg_doc, player_folder, user):
    """
    Create a Document record in the Documents app for a registration document.
    The file stays in Cloudinary; Google Drive upload happens on-demand when editing.
    
    Args:
        reg_doc: PlayerRegistrationDocument instance
        player_folder: Folder instance (player's personal folder in DB)
        user: User instance (the new player user)
    
    Returns:
        Document instance (the synced document in Documents app)
    """
    if not reg_doc.file:
        print(f"No file found for document: {reg_doc.title}")
        return None
    
    try:
        # Get file extension
        ext = reg_doc.file_extension or os.path.splitext(reg_doc.title)[1]
        if not ext.startswith('.'):
            ext = f'.{ext}'
        
        # Get the Cloudinary URL
        cloudinary_url = reg_doc.file.url
        
        # Create Document record in the Documents app
        # Store Cloudinary URL - player can view/download immediately
        # When they want to edit, they'll upload to Google Drive via OAuth
        # Note: needs_google_drive_upload is a computed property (cloudinary_url exists but no google_drive_id)
        doc = Document.objects.create(
            title=reg_doc.title,
            cloudinary_url=cloudinary_url,  # Store Cloudinary URL for viewing/downloading
            file_extension=ext,
            folder=player_folder,
            uploaded_by=user,
            owner=user,
            description=f"Registration document: {reg_doc.get_document_type_display()}"
        )
        
        # Link the registration document to the synced document
        reg_doc.synced_document = doc
        reg_doc.save(update_fields=['synced_document'])
        
        print(f"✓ Synced {reg_doc.title} to Documents app (ID: {doc.id})")
        
        return doc
        
    except Exception as e:
        print(f"Error syncing document to Documents app: {e}")
        raise


def transfer_all_registration_documents(registration, player_folder, user):
    """
    Sync all documents from a registration to the Documents app.
    
    Args:
        registration: PlayerRegistration instance
        player_folder: Folder instance (player's personal folder in DB)
        user: User instance (the new player)
    
    Returns:
        List of Document instances created
    """
    synced_docs = []
    
    for reg_doc in registration.documents.all():
        try:
            doc = sync_registration_document_to_documents_app(reg_doc, player_folder, user)
            if doc:
                synced_docs.append(doc)
        except Exception as e:
            print(f"Failed to sync document {reg_doc.title}: {e}")
            # Continue with other documents even if one fails
    
    return synced_docs
