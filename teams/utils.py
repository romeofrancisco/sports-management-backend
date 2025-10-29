"""
Utility functions for the teams app
"""
import os
from uuid import uuid4
from django.utils.text import slugify


def generate_upload_path(folder_name, instance, filename, identifier_field=None, max_filename_length=50):
    """
    Generate a safe upload path for images/files with filename truncation.
    
    Args:
        folder_name (str): The folder name where files will be uploaded (e.g., 'team_logos', 'player_photos')
        instance: The model instance being saved
        filename (str): Original filename from upload
        identifier_field (str, optional): Field name to use for generating safe filename (e.g., 'slug', 'name')
        max_filename_length (int): Maximum length for the filename (default: 50)
    
    Returns:
        str: Safe upload path with truncated filename
    
    Examples:
        # For team logos using slug
        upload_to=lambda instance, filename: generate_upload_path('team_logos', instance, filename, 'slug')
        
        # For player photos using user's name
        upload_to=lambda instance, filename: generate_upload_path('player_photos', instance, filename, 'user')
        
        # For generic uploads without identifier
        upload_to=lambda instance, filename: generate_upload_path('documents', instance, filename)
    """
    # Get the file extension
    ext = os.path.splitext(filename)[1].lower()  # e.g., '.jpg', '.png'
    
    # Generate base filename
    if identifier_field:
        # Try to get the identifier value from the instance
        try:
            if '.' in identifier_field:
                # Handle nested fields like 'user.first_name'
                parts = identifier_field.split('.')
                value = instance
                for part in parts:
                    value = getattr(value, part)
                identifier = str(value)
            else:
                identifier = getattr(instance, identifier_field, None)
            
            if identifier:
                # Slugify the identifier for safe filename
                safe_base = slugify(str(identifier))
            else:
                # Fallback to UUID if identifier is empty
                safe_base = f"{folder_name}_{uuid4().hex[:8]}"
        except (AttributeError, Exception):
            # Fallback to UUID if field doesn't exist or any error
            safe_base = f"{folder_name}_{uuid4().hex[:8]}"
    else:
        # No identifier provided, use UUID
        safe_base = f"{folder_name}_{uuid4().hex[:8]}"
    
    # Create the full filename
    safe_name = f"{safe_base}{ext}"
    
    # Truncate if too long, preserving the extension
    if len(safe_name) > max_filename_length:
        # Calculate how much space we have for the base name
        available_length = max_filename_length - len(ext)
        # Truncate the base name
        safe_base_truncated = safe_base[:available_length]
        safe_name = f"{safe_base_truncated}{ext}"
    
    return os.path.join(folder_name, safe_name)


def team_logo_upload_path(instance, filename):
    """
    Generate upload path for team logos.
    Uses team slug as identifier.
    """
    return generate_upload_path('team_logos', instance, filename, identifier_field='slug')


def player_photo_upload_path(instance, filename):
    """
    Generate upload path for player photos.
    Uses player slug as identifier.
    """
    return generate_upload_path('player_photos', instance, filename, identifier_field='slug')


def coach_photo_upload_path(instance, filename):
    """
    Generate upload path for coach photos.
    Uses coach user's full name as identifier.
    """
    return generate_upload_path('coach_photos', instance, filename, identifier_field='user')
