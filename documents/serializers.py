from rest_framework import serializers
from .models import Folder, Document, DocumentPermission
from users.models import User


class UserSimpleSerializer(serializers.ModelSerializer):
    """Simple user serializer for nested representations"""
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'role']


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
    
    class Meta:
        model = Folder
        fields = [
            'id', 'name', 'folder_type', 'parent', 'owner', 
            'created_at', 'subfolders', 'full_path'
        ]
        read_only_fields = ['created_at']


class FolderCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating folders"""
    class Meta:
        model = Folder
        fields = ['id', 'name', 'folder_type', 'parent', 'owner']
    
    def validate(self, attrs):
        folder_type = attrs.get('folder_type')
        parent = attrs.get('parent')
        owner = attrs.get('owner')
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        
        # Validate folder hierarchy rules
        if folder_type == Folder.FolderType.PUBLIC and parent:
            raise serializers.ValidationError("Public folder cannot have a parent")
        
        if folder_type == Folder.FolderType.COACHES and parent:
            raise serializers.ValidationError("Coaches folder cannot have a parent")
        
        if folder_type == Folder.FolderType.ADMIN_PRIVATE and parent:
            raise serializers.ValidationError("Admin private folder cannot have a parent")
        
        if folder_type == Folder.FolderType.COACH_PERSONAL:
            if not parent or parent.folder_type != Folder.FolderType.COACHES:
                raise serializers.ValidationError("Coach personal folder must be inside Coaches folder")
            if not owner or not owner.is_coach:
                raise serializers.ValidationError("Coach personal folder must have a coach as owner")
            # Only admins may create coach personal folders via the API
            if user and not getattr(user, 'is_admin', False):
                raise serializers.ValidationError("Only admins can create coach personal folders")
        
        if folder_type == Folder.FolderType.PLAYERS:
            if not parent or parent.folder_type != Folder.FolderType.COACH_PERSONAL:
                raise serializers.ValidationError("Players folder must be inside a coach personal folder")
            # Only admin or the owning coach can create a Players folder
            if user and not getattr(user, 'is_admin', False):
                if not getattr(user, 'is_coach', False) or parent.owner != user:
                    raise serializers.ValidationError("Only the owning coach or admin can create a Players folder")
        
        if folder_type == Folder.FolderType.PLAYER_PERSONAL:
            if not parent or parent.folder_type != Folder.FolderType.PLAYERS:
                raise serializers.ValidationError("Player personal folder must be inside Players folder")
            if not owner or not owner.is_player:
                raise serializers.ValidationError("Player personal folder must have a player as owner")
            # Admin can create anywhere. Coaches can create player folders under their own Players folder.
            # Players can create their own personal folder (owner must be the requesting user).
            if user and not getattr(user, 'is_admin', False):
                if getattr(user, 'is_coach', False):
                    # parent.owner should be the coach user
                    if parent.parent is None or parent.parent.owner != user:
                        raise serializers.ValidationError("Coaches can only create player folders under their own Players folder")
                elif getattr(user, 'is_player', False):
                    if owner != user:
                        raise serializers.ValidationError("Players can only create their own personal folder")
                else:
                    raise serializers.ValidationError("You don't have permission to create player personal folders")
        
        return attrs


class DocumentListSerializer(serializers.ModelSerializer):
    """Serializer for listing documents"""
    uploaded_by = UserSimpleSerializer(read_only=True)
    owner = UserSimpleSerializer(read_only=True)
    folder_name = serializers.CharField(source='folder.name', read_only=True)
    file_size = serializers.SerializerMethodField()
    
    class Meta:
        model = Document
        fields = [
            'id', 'title', 'file', 'folder', 'folder_name', 'uploaded_by', 
            'owner', 'status', 'uploaded_at', 'updated_at', 'file_size', 'description'
        ]
        read_only_fields = ['uploaded_at', 'updated_at', 'status']
    
    def get_file_size(self, obj):
        try:
            return obj.file.size
        except:
            return None


class DocumentDetailSerializer(serializers.ModelSerializer):
    """Serializer for document details"""
    uploaded_by = UserSimpleSerializer(read_only=True)
    owner = UserSimpleSerializer(read_only=True)
    folder_detail = FolderListSerializer(source='folder', read_only=True)
    original_document_detail = serializers.SerializerMethodField()
    copies_count = serializers.SerializerMethodField()
    file_size = serializers.SerializerMethodField()
    
    class Meta:
        model = Document
        fields = [
            'id', 'title', 'file', 'folder', 'folder_detail', 'uploaded_by', 
            'owner', 'status', 'original_document', 'original_document_detail',
            'uploaded_at', 'updated_at', 'description', 'copies_count', 'file_size'
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


class DocumentCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating/uploading documents"""
    class Meta:
        model = Document
        fields = ['id', 'title', 'file', 'folder', 'description']
    
    def validate_folder(self, value):
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
        return super().create(validated_data)


class DocumentCopySerializer(serializers.Serializer):
    """Serializer for copying documents"""
    target_folder = serializers.PrimaryKeyRelatedField(queryset=Folder.objects.all())
    
    def validate_target_folder(self, value):
        user = self.context['request'].user
        
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
