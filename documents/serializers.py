import os
from rest_framework import serializers
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from .models import Folder, Document, DocumentPermission
from users.models import User


class UserSimpleSerializer(serializers.ModelSerializer):
    """Simple user serializer for nested representations"""
    class Meta:
        model = User
        fields = ['id', 'email', 'profile', 'first_name', 'last_name', 'role']


class FolderListSerializer(serializers.ModelSerializer):
    """Serializer for listing folders"""
    owner = UserSimpleSerializer(read_only=True)
    subfolder_count = serializers.SerializerMethodField()
    document_count = serializers.SerializerMethodField()
    full_path = serializers.CharField(source='get_full_path', read_only=True)
    
    class Meta:
        model = Folder
        fields = [
            'id', 'name', 'folder_type', 'parent', 'owner', 
            'created_at', 'subfolder_count', 'document_count', 'full_path'
        ]
        read_only_fields = ['created_at']
    
    def get_subfolder_count(self, obj):
        return obj.subfolders.count()
    
    def get_document_count(self, obj):
        return obj.documents.count()


class FolderDetailSerializer(serializers.ModelSerializer):
    """Serializer for folder details with subfolders and documents"""
    owner = UserSimpleSerializer(read_only=True)
    subfolders = FolderListSerializer(many=True, read_only=True)
    full_path = serializers.CharField(source='get_full_path', read_only=True)
    breadcrumbs = serializers.SerializerMethodField()
    
    class Meta:
        model = Folder
        fields = [
            'id', 'name', 'folder_type', 'parent', 'owner', 
            'created_at', 'subfolders', 'full_path', 'breadcrumbs'
        ]
        read_only_fields = ['created_at']
    
    def get_breadcrumbs(self, obj):
        """Build breadcrumb trail from root to current folder"""
        breadcrumbs = []
        current = obj
        
        while current:
            breadcrumbs.insert(0, {
                'id': current.id,
                'name': current.name,
                'folder_type': current.folder_type,
            })
            current = current.parent
        
        return breadcrumbs


class FolderCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating folders - simplified for user-created subfolders"""
    description = serializers.CharField(required=False, allow_blank=True)
    folder_type = serializers.CharField(required=False, allow_blank=True)
    
    class Meta:
        model = Folder
        fields = ['id', 'name', 'parent', 'description', 'folder_type']
    
    def validate(self, attrs):
        """Validate folder name uniqueness within the same parent"""
        name = attrs.get('name')
        parent = attrs.get('parent')
        
        # Check for duplicate folder names in the same parent (exact match to match DB constraint)
        existing = Folder.objects.filter(
            name=name,
            parent=parent
        )
        
        # Exclude current instance if updating (though this is create-only)
        if self.instance:
            existing = existing.exclude(pk=self.instance.pk)
        
        if existing.exists():
            raise serializers.ValidationError({
                'name': f"A folder named '{name}' already exists."
            })
        
        return attrs
    
    def create(self, validated_data):
        request = self.context.get('request')
        user = request.user
        parent = validated_data.get('parent')
        description = validated_data.pop('description', None)  # Remove description since it's not a model field
        explicit_folder_type = validated_data.pop('folder_type', None)  # Get explicit folder type if provided
        
        # Determine folder_type and owner based on parent and user role
        if not parent:
            # Creating root-level folder
            if explicit_folder_type:
                # User explicitly specified folder type (admin/coach creating specific types)
                folder_type = explicit_folder_type
                
                # Validate permissions for explicit folder types
                if folder_type == 'public':
                    if not user.is_admin:
                        raise serializers.ValidationError("Only admins can create Public folders")
                    validated_data['folder_type'] = Folder.FolderType.PUBLIC
                    validated_data['owner'] = user
                    
                elif folder_type == 'coaches':
                    if not user.is_admin:
                        raise serializers.ValidationError("Only admins can create Coaches folders")
                    validated_data['folder_type'] = Folder.FolderType.COACHES
                    validated_data['owner'] = user
                    
                elif folder_type == 'admin_private':
                    if not user.is_admin:
                        raise serializers.ValidationError("Only admins can create Admin Private folders")
                    validated_data['folder_type'] = Folder.FolderType.ADMIN_PRIVATE
                    validated_data['owner'] = user
                    
                elif folder_type == 'coach_personal':
                    if not user.is_coach and not user.is_admin:
                        raise serializers.ValidationError("Only coaches can create Coach Personal folders")
                    validated_data['folder_type'] = Folder.FolderType.COACH_PERSONAL
                    validated_data['owner'] = user
                    
                else:
                    raise serializers.ValidationError(f"Invalid folder type: {folder_type}")
            else:
                # No explicit type - use default behavior
                if user.is_admin:
                    # Admin can create admin_private folders at root
                    validated_data['folder_type'] = Folder.FolderType.ADMIN_PRIVATE
                    validated_data['owner'] = user
                else:
                    raise serializers.ValidationError("Only admins can create root-level folders")
        else:
            # Creating subfolder - inherit type based on parent
            parent_type = parent.folder_type
            
            if parent_type == Folder.FolderType.PUBLIC:
                if not user.is_admin:
                    raise serializers.ValidationError("Only admins can create folders in Public folder")
                validated_data['folder_type'] = Folder.FolderType.PUBLIC
                validated_data['owner'] = user
            
            elif parent_type == Folder.FolderType.ADMIN_PRIVATE:
                if not user.is_admin:
                    raise serializers.ValidationError("Only admins can create folders in Admin Private folder")
                validated_data['folder_type'] = Folder.FolderType.ADMIN_PRIVATE
                validated_data['owner'] = user
            
            elif parent_type == Folder.FolderType.COACH_PERSONAL:
                # Subfolder in coach's personal folder
                if not user.is_admin and parent.owner != user:
                    raise serializers.ValidationError("You can only create folders in your own personal folder")
                validated_data['folder_type'] = Folder.FolderType.COACH_PERSONAL
                validated_data['owner'] = parent.owner
            
            elif parent_type == Folder.FolderType.PLAYER_PERSONAL:
                # Subfolder in player's personal folder
                if not user.is_admin and parent.owner != user:
                    # Check if user is the coach who owns the parent Players folder
                    if not (user.is_coach and parent.parent and parent.parent.parent and parent.parent.parent.owner == user):
                        raise serializers.ValidationError("You can only create folders in your own personal folder")
                validated_data['folder_type'] = Folder.FolderType.PLAYER_PERSONAL
                validated_data['owner'] = parent.owner
            
            elif parent_type == Folder.FolderType.PLAYERS:
                # Only admin or owning coach can create folders in Players folder
                if not user.is_admin:
                    if not (user.is_coach and parent.parent and parent.parent.owner == user):
                        raise serializers.ValidationError("You can only create folders under your own Players folder")
                validated_data['folder_type'] = Folder.FolderType.PLAYERS
                validated_data['owner'] = parent.parent.owner if parent.parent else user
            
            else:
                raise serializers.ValidationError(f"Cannot create subfolders in {parent_type} folder")
        
        # Try to create the folder and catch ValidationError or IntegrityError from model
        try:
            return super().create(validated_data)
        except ValidationError as e:
            # Convert Django ValidationError to DRF ValidationError
            if hasattr(e, 'message_dict'):
                raise serializers.ValidationError(e.message_dict)
            else:
                raise serializers.ValidationError(str(e))
        except IntegrityError as e:
            # Handle unique constraint violation at database level
            error_message = str(e).lower()
            folder_name = validated_data.get('name', 'this folder')
            
            # Check for various forms of unique constraint violations
            if any(keyword in error_message for keyword in [
                'unique constraint', 
                'unique_together', 
                'duplicate key',
                'unique_folder_name_per_parent',
                'must make a unique set'
            ]):
                raise serializers.ValidationError({
                    'name': f"A folder named '{folder_name}' already exists."
                })
            else:
                raise serializers.ValidationError({
                    'name': "Unable to create folder. Please try a different name."
                })


class DocumentListSerializer(serializers.ModelSerializer):
    """Serializer for listing documents"""
    uploaded_by = UserSimpleSerializer(read_only=True)
    owner = UserSimpleSerializer(read_only=True)
    folder_name = serializers.CharField(source='folder.name', read_only=True)
    file_size = serializers.SerializerMethodField()
    file_extension = serializers.SerializerMethodField()
    
    class Meta:
        model = Document
        fields = [
            'id', 'title', 'file', 'folder', 'folder_name', 'uploaded_by', 
            'owner', 'status', 'uploaded_at', 'updated_at', 'file_size', 'file_extension', 'description'
        ]
        read_only_fields = ['uploaded_at', 'updated_at', 'status']
    
    def get_file_size(self, obj):
        try:
            return obj.file.size
        except:
            return None
    
    def get_file_extension(self, obj):
        """Return the stored file extension"""
        if obj.file_extension:
            return obj.file_extension.upper()
        return 'FILE'


class DocumentDetailSerializer(serializers.ModelSerializer):
    """Serializer for document details"""
    uploaded_by = UserSimpleSerializer(read_only=True)
    owner = UserSimpleSerializer(read_only=True)
    folder_detail = FolderListSerializer(source='folder', read_only=True)
    original_document_detail = serializers.SerializerMethodField()
    copies_count = serializers.SerializerMethodField()
    file_size = serializers.SerializerMethodField()
    file_extension = serializers.SerializerMethodField()
    
    class Meta:
        model = Document
        fields = [
            'id', 'title', 'file', 'folder', 'folder_detail', 'uploaded_by', 
            'owner', 'status', 'original_document', 'original_document_detail',
            'uploaded_at', 'updated_at', 'description', 'copies_count', 'file_size', 'file_extension'
        ]
        read_only_fields = ['uploaded_at', 'updated_at', 'status', 'original_document']
    
    def get_original_document_detail(self, obj):
        if obj.original_document:
            return {
                'id': obj.original_document.id,
                'title': obj.original_document.title,
                'owner': UserSimpleSerializer(obj.original_document.owner).data
            }
        return None
    
    def get_copies_count(self, obj):
        return obj.copies.count()
    
    def get_file_size(self, obj):
        try:
            return obj.file.size
        except:
            return None
    
    def get_file_extension(self, obj):
        """Return the stored file extension"""
        if obj.file_extension:
            return obj.file_extension.upper()
        return 'FILE'


class DocumentCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating/uploading documents"""
    folder = serializers.PrimaryKeyRelatedField(
        queryset=Folder.objects.all(),
        required=False,
        allow_null=True
    )
    
    class Meta:
        model = Document
        fields = ['id', 'title', 'file', 'folder', 'description']
    
    def validate(self, attrs):
        """Validate that document title is unique within the same folder"""
        title = attrs.get('title')
        folder = attrs.get('folder')
        user = self.context['request'].user
        
        # Folder is required for non-admin users
        if not user.is_admin and not folder:
            raise serializers.ValidationError({
                'folder': 'Folder is required for non-admin users.'
            })
        
        # Check if a document with the same title exists in the same folder
        duplicate_query = Document.objects.filter(
            title=title,
            folder=folder
        )
        
        if duplicate_query.exists():
            raise serializers.ValidationError({
                'title': f"A file named '{title}' already exists."
            })
        
        return attrs
    
    def validate_folder(self, value):
        # Allow null folder for admins
        if value is None:
            user = self.context['request'].user
            if user.is_admin:
                return value
            raise serializers.ValidationError("Folder is required for non-admin users")
        
        user = self.context['request'].user
        
        # Check if user can upload to this folder
        if not user.is_admin:
            if value.folder_type == Folder.FolderType.PUBLIC:
                raise serializers.ValidationError("Only admins can upload to Public folder")
            if value.folder_type == Folder.FolderType.COACHES:
                raise serializers.ValidationError("Cannot upload directly to Coaches folder")
            if value.folder_type == Folder.FolderType.PLAYERS:
                raise serializers.ValidationError("Cannot upload directly to Players folder")
            
            # Users can only upload to their own personal folders
            if value.owner != user:
                raise serializers.ValidationError("You can only upload to your own folder")
        
        return value
    
    def create(self, validated_data):
        user = self.context['request'].user
        validated_data['uploaded_by'] = user
        validated_data['owner'] = user
        
        # Extract and store the file extension
        file = validated_data.get('file')
        if file:
            original_name = file.name
            _, ext = os.path.splitext(original_name)
            
            # Store extension without the dot (e.g., 'pdf', 'docx')
            if ext and len(ext) > 1:
                validated_data['file_extension'] = ext[1:].lower()
        
        try:
            return super().create(validated_data)
        except ValidationError:
            raise
        except IntegrityError as e:
            title = validated_data.get('title')
            raise serializers.ValidationError({
                'title': f"A file named '{title}' already exists."
            })



class DocumentCopySerializer(serializers.Serializer):
    """Serializer for copying documents"""
    target_folder = serializers.PrimaryKeyRelatedField(
        queryset=Folder.objects.all(),
        required=False,
        allow_null=True
    )
    
    def validate_target_folder(self, value):
        user = self.context['request'].user
        
        # Admin can copy to null (root level)
        if value is None:
            if not user.is_admin:
                raise serializers.ValidationError("Only admins can copy to root level")
            return value
        
        if not value.can_access(user):
            raise serializers.ValidationError("You cannot access the target folder")
        
        # Users can only copy to their own personal folders
        if not user.is_admin and value.owner != user:
            raise serializers.ValidationError("You can only copy to your own folder")
        
        return value


class DocumentPermissionSerializer(serializers.ModelSerializer):
    """Serializer for document permissions"""
    user = UserSimpleSerializer(read_only=True)
    granted_by = UserSimpleSerializer(read_only=True)
    
    class Meta:
        model = DocumentPermission
        fields = ['id', 'document', 'user', 'can_view', 'can_edit', 'can_delete', 'granted_by', 'granted_at']
        read_only_fields = ['granted_at']
