from django.db import models
from users.models import User
from django.core.exceptions import ValidationError

class Folder(models.Model):
    """Represents a folder in the hierarchy"""
    class FolderType(models.TextChoices):
        PUBLIC = "public", "Public"
        COACHES = "coaches", "Coaches"
        COACH_PERSONAL = "coach_personal", "Coach Personal"
        PLAYERS = "players", "Players"
        PLAYER_PERSONAL = "player_personal", "Player Personal"
        ADMIN_PRIVATE = "admin_private", "Admin Private"
    
    name = models.CharField(max_length=255)
    folder_type = models.CharField(max_length=20, choices=FolderType.choices)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subfolders')
    owner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='owned_folders')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
        # No database-level unique constraint - we handle validation in serializer and model clean()
    
    def __str__(self):
        return f"{self.name} ({self.folder_type})"
    
    def clean(self):
        """Validate folder name uniqueness within the same parent"""
        # Check for duplicate folder names in the same parent (exact match)
        existing = Folder.objects.filter(
            name=self.name,
            parent=self.parent
        ).exclude(pk=self.pk)
        
        if existing.exists():
            raise ValidationError({
                'name': f"A folder named '{self.name}' already exists."
            })
    
    def save(self, *args, **kwargs):
        """Override save to call clean validation"""
        self.clean()
        super().save(*args, **kwargs)
    
    def get_full_path(self):
        """Returns the full path of the folder using a special separator that won't conflict with folder names"""
        if self.parent:
            return f"{self.parent.get_full_path()} > {self.name}"
        return self.name
    
    def can_access(self, user):
        """Check if user can access this folder"""
        if user.is_admin:
            return True
        
        if self.folder_type == self.FolderType.PUBLIC:
            return True
        
        if self.folder_type == self.FolderType.COACHES:
            # Admin and coaches can access Coaches type folders
            return user.is_admin or user.is_coach
        
        if self.folder_type == self.FolderType.COACH_PERSONAL and user.is_coach:
            # Coach can only access their own personal folder
            return self.owner == user
        
        if self.folder_type == self.FolderType.PLAYER_PERSONAL:
            if user.is_player:
                # Player can access their own folder
                return self.owner == user
            if user.is_coach:
                # Coach can access player folders under their Players folder
                return self.parent and self.parent.parent and self.parent.parent.owner == user
        
        if self.folder_type == self.FolderType.PLAYERS and user.is_coach:
            # Coach can access their players' folder
            return self.parent and self.parent.owner == user
        
        if self.folder_type == self.FolderType.ADMIN_PRIVATE:
            # Only admin can access private folders
            return user.is_admin
        
        return False


class Document(models.Model):
    """Represents a document in the system"""
    class DocumentStatus(models.TextChoices):
        ORIGINAL = "original", "Original"
        COPY = "copy", "Copy"
    
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to='documents/')
    file_extension = models.CharField(max_length=10, blank=True)
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name='documents', null=True, blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='uploaded_documents')
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_documents')
    status = models.CharField(max_length=10, choices=DocumentStatus.choices, default=DocumentStatus.ORIGINAL)
    original_document = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='copies')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    description = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return f"{self.title} - {self.status}"
    
    def clean(self):
        """Validate that document title is unique within the same folder"""
        super().clean()
        
        # Check for duplicate document title in the same folder
        duplicate_query = Document.objects.filter(
            title=self.title,
            folder=self.folder
        )
        
        # Exclude current instance if updating
        if self.pk:
            duplicate_query = duplicate_query.exclude(pk=self.pk)
        
        if duplicate_query.exists():
            raise ValidationError({
                'title': f"A file named '{self.title}' already exists."
            })
    
    def save(self, *args, **kwargs):
        """Override save to call clean() before saving"""
        self.clean()
        super().save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        """Override delete to remove the file from filesystem or cloud storage"""
        # Delete the file from storage (works with local and cloud storage)
        if self.file:
            try:
                self.file.delete(save=False)
            except Exception as e:
                # Log the error but don't prevent deletion
                print(f"Error deleting file: {e}")
        
        # Call the parent delete method
        super().delete(*args, **kwargs)
    
    def can_view(self, user):
        """Check if user can view this document"""
        return self.folder.can_access(user)
    
    def can_edit(self, user):
        """Check if user can edit this document (original file)"""
        if user.is_admin:
            return True
        
        # Only owner can edit their original files
        if self.status == self.DocumentStatus.ORIGINAL:
            return self.owner == user
        
        # Users can edit their copies
        return self.owner == user
    
    def can_delete(self, user):
        """Check if user can delete this document"""
        if user.is_admin:
            return True
        
        # Users can delete their own files
        return self.owner == user
    
    def create_copy(self, user, target_folder):
        """Create a copy of this document for a user"""
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage
        import os
        
        # Check if user can access target folder (null folder is admin-only)
        if target_folder is None:
            if not user.is_admin:
                raise ValidationError("Only admins can copy to root level")
        elif not target_folder.can_access(user):
            raise ValidationError("User cannot access target folder")
        
        # Create a physical copy of the file using Django's file field methods
        new_file = None
        if self.file:
            try:
                # Use the file field's open method which handles storage correctly
                self.file.open('rb')
                original_content = self.file.read()
                self.file.close()
                
                # Get the original filename and create a new name for the copy
                original_name = os.path.basename(self.file.name)
                name, ext = os.path.splitext(original_name)
                new_filename = f"{name}_copy{ext}"
                
                # Create a new file with the copied content
                new_file = ContentFile(original_content, name=new_filename)
            except Exception as e:
                raise ValidationError(f"Error copying file: {str(e)}")
        
        copy = Document.objects.create(
            title=f"{self.title} (Copy)",
            file=new_file,
            file_extension=self.file_extension,
            folder=target_folder,
            uploaded_by=user,
            owner=user,
            status=self.DocumentStatus.COPY,
            original_document=self if self.status == self.DocumentStatus.ORIGINAL else self.original_document,
            description=self.description
        )
        return copy


class DocumentPermission(models.Model):
    """Additional permissions for documents"""
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='permissions')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    can_view = models.BooleanField(default=True)
    can_edit = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    granted_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='granted_permissions')
    granted_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = [['document', 'user']]
    
    def __str__(self):
        return f"{self.user.email} - {self.document.title}"