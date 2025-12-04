from django.db.models.signals import pre_delete, post_delete
from django.dispatch import receiver
from .models import PlayerRegistration, PlayerRegistrationDocument


@receiver(pre_delete, sender=PlayerRegistration)
def cleanup_registration_documents_on_registration_delete(sender, instance, **kwargs):
    """
    When a player registration is deleted, clean up the synced documents
    and the registration document files.
    """
    for reg_doc in instance.documents.all():
        # Delete synced document in the Documents app
        if reg_doc.synced_document:
            try:
                synced_doc = reg_doc.synced_document
                reg_doc.synced_document = None
                reg_doc.save(update_fields=['synced_document'])
                synced_doc.delete()
            except Exception as e:
                print(f"Error deleting synced document: {e}")
        
        # Delete the uploaded file
        if reg_doc.file:
            try:
                reg_doc.file.delete(save=False)
            except Exception as e:
                print(f"Error deleting registration document file: {e}")


@receiver(pre_delete, sender=PlayerRegistrationDocument)
def cleanup_synced_document_on_registration_doc_delete(sender, instance, **kwargs):
    """
    When a registration document is deleted, also delete the synced document
    in the Documents app if it exists.
    """
    if instance.synced_document:
        try:
            synced_doc = instance.synced_document
            instance.synced_document = None
            # Don't save here as the instance is being deleted
            synced_doc.delete()
        except Exception as e:
            print(f"Error deleting synced document: {e}")
    
    # Delete the uploaded file
    if instance.file:
        try:
            instance.file.delete(save=False)
        except Exception as e:
            print(f"Error deleting registration document file: {e}")
