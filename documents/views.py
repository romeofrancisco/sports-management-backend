from django.shortcuts import render, get_object_or_404
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from .models import Folder, Document, DocumentPermission
from .serializers import (
    FolderListSerializer, FolderDetailSerializer, FolderCreateSerializer,
    DocumentListSerializer, DocumentDetailSerializer, DocumentCreateSerializer,
    DocumentCopySerializer, DocumentPermissionSerializer
)
from .folder_utils import get_user_personal_folder, ensure_root_folders


class FolderViewSet(viewsets.ModelViewSet):
    """ViewSet for managing folders"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """
        Optimized queryset - only returns folders the user should see.
        For list view, returns only accessible folders.
        For detail view, checks access permission.
        """
        user = self.request.user
        
        # For retrieve action, we check permission in retrieve method
        # For list action, we return empty to force using root_folders or contents endpoints
        if self.action == 'list':
            # Return empty queryset for list - users should use root_folders endpoint
            return Folder.objects.none()
        
        # For other actions (retrieve, update, delete), return accessible folders
        if user.is_admin:
            return Folder.objects.all()
        
        # Build query based on user role
        query = Q(folder_type=Folder.FolderType.PUBLIC)
        
        if user.is_coach:
            # Coach can see their own folders and their players' folders
            query |= Q(folder_type=Folder.FolderType.COACH_PERSONAL, owner=user)
            query |= Q(folder_type=Folder.FolderType.PLAYERS, parent__owner=user)
            query |= Q(folder_type=Folder.FolderType.PLAYER_PERSONAL, parent__parent__owner=user)
            query |= Q(folder_type=Folder.FolderType.COACHES)
        
        if user.is_player:
            # Player can see their own folder
            query |= Q(folder_type=Folder.FolderType.PLAYER_PERSONAL, owner=user)
        
        return Folder.objects.filter(query).distinct()
    
    def get_serializer_class(self):
        if self.action == 'create':
            return FolderCreateSerializer
        elif self.action == 'retrieve':
            return FolderDetailSerializer
        return FolderListSerializer
    
    def perform_create(self, serializer):
        # The serializer now handles all the logic for determining folder_type and owner
        serializer.save()
    
    @action(detail=True, methods=['get'])
    def contents(self, request, pk=None):
        """
        Get folder contents (subfolders and documents).
        Optimized with select_related and prefetch_related.
        Coaches only see their own folder when browsing Coaches root folder.
        Coaches only see player folders for their assigned players.
        """
        folder = self.get_object()
        
        if not folder.can_access(request.user):
            return Response(
                {"error": "You don't have permission to access this folder"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Optimize queries with select_related for foreign keys
        subfolders = folder.subfolders.select_related('owner').all()
        
        # Filter subfolders based on user role
        if folder.folder_type == Folder.FolderType.COACHES and request.user.is_coach:
            # Coaches only see their own personal folder inside Coaches folder
            subfolders = subfolders.filter(owner=request.user)
        elif folder.folder_type == Folder.FolderType.PLAYERS and request.user.is_coach:
            # Coaches only see player folders for players in their teams
            from teams.models import Team
            
            # Get teams coached by this coach
            coached_teams = Team.objects.filter(
                Q(head_coach__user=request.user) | Q(assistant_coach__user=request.user)
            )
            
            # Get player users from these teams
            from users.models import User
            player_users = User.objects.filter(
                role=User.Role.PLAYER,
                player_profile__team__in=coached_teams
            ).distinct()
            
            # Filter subfolders to only show folders owned by these players
            subfolders = subfolders.filter(owner__in=player_users)
        
        documents = folder.documents.select_related('folder', 'owner', 'uploaded_by').all()
        
        return Response({
            'folder': FolderDetailSerializer(folder).data,
            'subfolders': FolderListSerializer(subfolders, many=True).data,
            'documents': DocumentListSerializer(documents, many=True).data
        })
    
    @action(detail=False, methods=['get'])
    def root_folders(self, request):
        """
        Get root folders accessible by user.
        Only returns top-level folders, not nested structure.
        Optimized to avoid loading all folders.
        
        AUTO-RECOVERY: If personal folders are missing, they will be automatically recreated.
        """
        user = request.user
        
        # Ensure root folders exist (auto-recovery)
        ensure_root_folders()
        
        root_folders = []
        
        # Public folder (always visible to all users)
        public_folder = Folder.objects.filter(
            folder_type=Folder.FolderType.PUBLIC,
            parent__isnull=True
        ).first()
        if public_folder:
            root_folders.append(public_folder)
        
        if user.is_admin:
            # Admin can see Coaches and Admin Private folders
            coaches_folder = Folder.objects.filter(
                folder_type=Folder.FolderType.COACHES,
                parent__isnull=True
            ).first()
            if coaches_folder:
                root_folders.append(coaches_folder)
            
            # Get all admin private folders (root level only)
            admin_folders = Folder.objects.filter(
                folder_type=Folder.FolderType.ADMIN_PRIVATE,
                parent__isnull=True
            )
            root_folders.extend(list(admin_folders))
        
        if user.is_coach:
            # Coach sees the CONTENTS of their personal folder directly at root
            # Not the folder itself, but what's inside it (Players folder, their documents, etc.)
            # AUTO-RECOVERY: Get or create coach's personal folder
            coach_folder = get_user_personal_folder(user)
            
            if coach_folder:
                # Get subfolders inside the coach's personal folder
                coach_subfolders = coach_folder.subfolders.select_related('owner').all()
                root_folders.extend(list(coach_subfolders))
        
        if user.is_player:
            # Player sees the CONTENTS of their personal folder directly at root
            # Not the folder itself, but what's inside it (subfolders and documents)
            # AUTO-RECOVERY: Get or create player's personal folder
            player_folder = get_user_personal_folder(user)
            
            if player_folder:
                # Get subfolders inside the player's personal folder
                player_subfolders = player_folder.subfolders.select_related('owner').all()
                root_folders.extend(list(player_subfolders))
        
        # By default return only folders. For coaches/players we also surface documents
        result = {
            'folders': FolderListSerializer(root_folders, many=True).data
        }

        # If coach, include documents directly under their personal folder and the folder ID
        if user.is_coach and coach_folder:
            coach_documents = coach_folder.documents.select_related('owner', 'uploaded_by').all()
            result['documents'] = DocumentListSerializer(coach_documents, many=True).data
            result['personal_folder_id'] = coach_folder.id  # Add personal folder ID for uploads/folder creation

        # If player, include documents directly under their personal folder and the folder ID
        if user.is_player and player_folder:
            player_documents = player_folder.documents.select_related('owner', 'uploaded_by').all()
            # Merge with any existing documents key
            if 'documents' in result:
                result['documents'].extend(DocumentListSerializer(player_documents, many=True).data)
            else:
                result['documents'] = DocumentListSerializer(player_documents, many=True).data
            result['personal_folder_id'] = player_folder.id  # Add personal folder ID for uploads/folder creation

        return Response(result)

    @action(detail=False, methods=['get'])
    def personal_folder(self, request):
        """
        Get the user's personal folder for copy operations.
        Returns the folder ID that non-admin users should copy files to.
        
        AUTO-RECOVERY: If personal folder is missing, it will be automatically recreated.
        """
        user = request.user
        
        if user.is_admin:
            return Response({
                'error': 'Admins do not have a specific personal folder'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Use auto-recovery utility
        personal_folder = get_user_personal_folder(user)
        
        if not personal_folder:
            return Response({
                'error': 'Personal folder not found. Please contact administrator.'
            }, status=status.HTTP_404_NOT_FOUND)
        
        return Response({
            'id': personal_folder.id,
            'name': personal_folder.name,
            'folder_type': personal_folder.folder_type
        })


class DocumentViewSet(viewsets.ModelViewSet):
    """ViewSet for managing documents"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """
        Optimized queryset - uses Q objects instead of building lists.
        For list view, returns empty to force using folder contents endpoint.
        """
        user = self.request.user
        
        # For list action, return empty queryset - users should use folder contents endpoint
        if self.action == 'list':
            return Document.objects.none()
        
        # For other actions (retrieve, update, delete), return accessible documents
        if user.is_admin:
            return Document.objects.select_related('folder', 'owner', 'uploaded_by').all()
        
        # Build query based on user role using Q objects (more efficient)
        query = Q(folder__folder_type=Folder.FolderType.PUBLIC)
        
        if user.is_coach:
            # Coach's own documents
            query |= Q(folder__folder_type=Folder.FolderType.COACH_PERSONAL, folder__owner=user)
            query |= Q(folder__folder_type=Folder.FolderType.PLAYERS, folder__parent__owner=user)
            query |= Q(folder__folder_type=Folder.FolderType.PLAYER_PERSONAL, folder__parent__parent__owner=user)
        
        if user.is_player:
            # Player's own documents
            query |= Q(folder__folder_type=Folder.FolderType.PLAYER_PERSONAL, folder__owner=user)
        
        return Document.objects.select_related('folder', 'owner', 'uploaded_by').filter(query).distinct()
    
    def get_serializer_class(self):
        if self.action == 'create':
            return DocumentCreateSerializer
        elif self.action == 'retrieve':
            return DocumentDetailSerializer
        elif self.action == 'copy':
            return DocumentCopySerializer
        return DocumentListSerializer
    
    def retrieve(self, request, *args, **kwargs):
        document = self.get_object()
        
        if not document.can_view(request.user):
            return Response(
                {"error": "You don't have permission to view this document"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return super().retrieve(request, *args, **kwargs)
    
    def update(self, request, *args, **kwargs):
        document = self.get_object()
        
        if not document.can_edit(request.user):
            return Response(
                {"error": "You don't have permission to edit this document"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return super().update(request, *args, **kwargs)
    
    def destroy(self, request, *args, **kwargs):
        document = self.get_object()
        
        if not document.can_delete(request.user):
            return Response(
                {"error": "You don't have permission to delete this document"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return super().destroy(request, *args, **kwargs)
    
    @action(detail=True, methods=['post'])
    def copy(self, request, pk=None):
        """Create a copy of a document"""
        document = self.get_object()
        
        if not document.can_view(request.user):
            return Response(
                {"error": "You don't have permission to view this document"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        target_folder = serializer.validated_data['target_folder']
        
        try:
            copy = document.create_copy(request.user, target_folder)
            return Response(
                DocumentDetailSerializer(copy).data,
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['patch'])
    def rename(self, request, pk=None):
        """Rename a document"""
        import cloudinary.uploader
        import os
        
        document = self.get_object()
        
        if not document.can_edit(request.user):
            return Response(
                {"error": "You don't have permission to rename this document"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        new_title = request.data.get('title')
        if not new_title:
            return Response(
                {"error": "New title is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get the old file and extract the public_id from the file field
        if document.file:
            try:
                # Get the file name from the FileField (this is the path stored in database)
                # Format: documents/filename.ext
                old_file_name = document.file.name
                
                # Get the file extension
                file_extension = os.path.splitext(old_file_name)[1]
                
                # Remove extension to get the public_id
                # The file.name is already the correct path without 'media/' prefix
                old_public_id = os.path.splitext(old_file_name)[0]
                
                # Create new public_id with the same folder structure but new filename
                # Keep the folder path (e.g., 'documents/'), just change the filename
                folder_path = os.path.dirname(old_public_id)
                new_filename = new_title.replace(' ', '_')  # Replace spaces with underscores
                new_public_id = os.path.join(folder_path, new_filename).replace('\\', '/')
                
                # Rename the file in Cloudinary
                # MediaCloudinaryStorage stores files as 'image' type by default
                # Try image first, fall back to raw if it fails
                try:
                    cloudinary.uploader.rename(
                        old_public_id,
                        new_public_id,
                        resource_type='image',
                        invalidate=True
                    )
                except Exception as img_error:
                    # If image fails, try raw
                    try:
                        cloudinary.uploader.rename(
                            old_public_id,
                            new_public_id,
                            resource_type='raw',
                            invalidate=True
                        )
                    except Exception as raw_error:
                        raise Exception(f"Failed with both image and raw types. Image error: {img_error}, Raw error: {raw_error}")
                
                # Update the document's file field with new public_id
                document.file.name = f"{new_public_id}{file_extension}"
                
            except Exception as e:
                return Response(
                    {"error": f"Failed to rename file in storage: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        
        # Update the title in database
        document.title = new_title
        document.save()
        
        return Response(
            DocumentDetailSerializer(document).data,
            status=status.HTTP_200_OK
        )
    
    @action(detail=True, methods=['get'])
    def copies(self, request, pk=None):
        """Get all copies of a document"""
        document = self.get_object()
        
        if not document.can_view(request.user):
            return Response(
                {"error": "You don't have permission to view this document"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        copies = document.copies.all()
        return Response(DocumentListSerializer(copies, many=True).data)
    
    @action(detail=False, methods=['get'])
    def my_documents(self, request):
        """Get documents owned by the current user"""
        documents = Document.objects.filter(owner=request.user)
        return Response(DocumentListSerializer(documents, many=True).data)


class DocumentPermissionViewSet(viewsets.ModelViewSet):
    """ViewSet for managing document permissions"""
    queryset = DocumentPermission.objects.all()
    serializer_class = DocumentPermissionSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        
        if user.is_admin:
            return DocumentPermission.objects.all()
        
        # Users can see permissions for their own documents
        return DocumentPermission.objects.filter(
            Q(document__owner=user) | Q(user=user)
        )
    
    def perform_create(self, serializer):
        document = serializer.validated_data['document']
        
        # Only document owner or admin can grant permissions
        if not (self.request.user.is_admin or document.owner == self.request.user):
            raise permissions.PermissionDenied("Only document owner or admin can grant permissions")
        
        serializer.save(granted_by=self.request.user)

