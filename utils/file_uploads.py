"""
Reusable utility functions for file uploads across the entire project.
This module provides safe upload path generation with filename truncation
to prevent database errors from long filenames.
"""
import os
from uuid import uuid4
from django.utils.text import slugify


def generate_upload_path(folder_name, instance, filename, identifier_field=None, max_filename_length=50):
    """
    Generate a safe upload path for images/files with filename truncation.
    
    This function creates safe upload paths by:
    - Using a model field as identifier (if provided)
    - Slugifying the identifier for URL-safe filenames
    - Truncating long filenames to prevent database errors
    - Preserving file extensions
    - Falling back to UUID if identifier is not available
    
    Args:
        folder_name (str): The folder name where files will be uploaded (e.g., 'team_logos', 'player_photos')
        instance: The model instance being saved
        filename (str): Original filename from upload
        identifier_field (str, optional): Field name to use for generating safe filename (e.g., 'slug', 'name', 'user.first_name')
        max_filename_length (int): Maximum length for the filename (default: 50)
    
    Returns:
        str: Safe upload path with truncated filename (e.g., 'team_logos/my-team-slug.jpg')
    
    Examples:
        # In models.py
        from utils.file_uploads import generate_upload_path
        
        # For team logos using slug
        logo = models.ImageField(
            upload_to=lambda instance, filename: generate_upload_path('team_logos', instance, filename, 'slug'),
            null=True, blank=True
        )
        
        # For user profiles using email
        profile = models.ImageField(
            upload_to=lambda instance, filename: generate_upload_path('profiles', instance, filename, 'email'),
            null=True, blank=True
        )
        
        # For player photos using nested field
        photo = models.ImageField(
            upload_to=lambda instance, filename: generate_upload_path('player_photos', instance, filename, 'user.first_name'),
            null=True, blank=True
        )
        
        # For generic uploads without identifier (uses UUID)
        document = models.FileField(
            upload_to=lambda instance, filename: generate_upload_path('documents', instance, filename)
        )
    """
    # Get the file extension
    ext = os.path.splitext(filename)[1].lower()  # e.g., '.jpg', '.png'
    
    # Generate base filename
    if identifier_field:
        # Try to get the identifier value from the instance
        try:
            if '.' in identifier_field:
                # Handle nested fields like 'user.first_name' or 'team.name'
                parts = identifier_field.split('.')
                value = instance
                for part in parts:
                    value = getattr(value, part)
                identifier = str(value)
            else:
                # Simple field like 'slug' or 'name'
                identifier = getattr(instance, identifier_field, None)
            
            if identifier:
                # Slugify the identifier for safe, URL-friendly filename
                safe_base = slugify(str(identifier))
            else:
                # Fallback to UUID if identifier is empty
                safe_base = f"{folder_name}_{uuid4().hex[:8]}"
        except (AttributeError, Exception):
            # Fallback to UUID if field doesn't exist or any error occurs
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
    
    # Return the full path
    return os.path.join(folder_name, safe_name)


# Pre-configured upload path functions for common use cases
def team_logo_upload_path(instance, filename):
    """Upload path for team logos. Uses team slug as identifier."""
    return generate_upload_path('team_logos', instance, filename, identifier_field='slug')


def player_photo_upload_path(instance, filename):
    """Upload path for player photos. Uses player slug as identifier."""
    return generate_upload_path('player_photos', instance, filename, identifier_field='slug')


def coach_photo_upload_path(instance, filename):
    """Upload path for coach photos. Uses coach user as identifier."""
    return generate_upload_path('coach_photos', instance, filename, identifier_field='user')


def user_profile_upload_path(instance, filename):
    """Upload path for user profile pictures. Uses user email as identifier."""
    return generate_upload_path('profiles', instance, filename, identifier_field='email')


def league_logo_upload_path(instance, filename):
    """Upload path for league logos. Uses league slug or name as identifier."""
    # Try slug first, fallback to name
    identifier = 'slug' if hasattr(instance, 'slug') and instance.slug else 'name'
    return generate_upload_path('league_logos', instance, filename, identifier_field=identifier)


def sport_banner_upload_path(instance, filename):
    """Upload path for sport banners. Uses sport name as identifier."""
    return generate_upload_path('sport_banners', instance, filename, identifier_field='name')


def facility_photo_upload_path(instance, filename):
    """Upload path for facility photos. Uses facility name as identifier."""
    return generate_upload_path('facility_images', instance, filename, identifier_field='name')
