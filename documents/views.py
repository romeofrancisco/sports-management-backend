from django.shortcuts import render, get_object_or_404
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from .models import Folder, Document, DocumentPermission
from .serializers import (
    FolderListSerializer,
    FolderDetailSerializer,
    FolderCreateSerializer,
    DocumentListSerializer,
    DocumentDetailSerializer,
    DocumentCreateSerializer,
    DocumentCopySerializer,
    DocumentPermissionSerializer,
)
from .folder_utils import get_user_personal_folder, ensure_root_folders
import cloudinary


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
        if self.action == "list":
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
            query |= Q(
                folder_type=Folder.FolderType.PLAYER_PERSONAL,
                parent__parent__owner=user,
            )
            query |= Q(folder_type=Folder.FolderType.COACHES)

        if user.is_player:
            # Player can see their own folder
            query |= Q(folder_type=Folder.FolderType.PLAYER_PERSONAL, owner=user)

        return Folder.objects.filter(query).distinct()

    def get_serializer_class(self):
        if self.action == "create":
            return FolderCreateSerializer
        elif self.action == "retrieve":
            return FolderDetailSerializer
        return FolderListSerializer

    def perform_create(self, serializer):
        # The serializer now handles all the logic for determining folder_type and owner
        serializer.save()

    @action(detail=True, methods=["get"])
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
                status=status.HTTP_403_FORBIDDEN,
            )

        # Optimize queries with select_related for foreign keys
        subfolders = folder.subfolders.select_related("owner").all()

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
                role=User.Role.PLAYER, player_profile__team__in=coached_teams
            ).distinct()

            # Filter subfolders to only show folders owned by these players
            subfolders = subfolders.filter(owner__in=player_users)

        documents = folder.documents.select_related(
            "folder", "owner", "uploaded_by"
        ).all()

        return Response(
            {
                "folder": FolderDetailSerializer(folder).data,
                "subfolders": FolderListSerializer(subfolders, many=True).data,
                "documents": DocumentListSerializer(documents, many=True).data,
            }
        )

    @action(detail=False, methods=["get"])
    def root_folders(self, request):
        """
        Get root folders accessible by user.
        Only returns top-level folders, not nested structure.
        Optimized to avoid loading all folders.

        AUTO-RECOVERY: If personal folders are missing, they will be automatically recreated.
        """
        user = request.user

        # Ensure root folders exist (auto-recovery)
        # ensure_root_folders()

        root_folders = []

        # Public folders (always visible to all users) - get ALL public root folders
        public_folders = Folder.objects.filter(
            folder_type=Folder.FolderType.PUBLIC, parent__isnull=True
        )
        root_folders.extend(list(public_folders))

        if user.is_admin:
            # Admin can see ALL Coaches and Admin Private folders
            # Get ALL coaches root folders (not just the first one)
            coaches_folders = Folder.objects.filter(
                folder_type=Folder.FolderType.COACHES, parent__isnull=True
            )
            root_folders.extend(list(coaches_folders))

            # Get all admin private folders (root level only)
            admin_folders = Folder.objects.filter(
                folder_type=Folder.FolderType.ADMIN_PRIVATE, parent__isnull=True
            )
            root_folders.extend(list(admin_folders))

        if user.is_coach:
            # Coaches can see admin-created coaches folders, but NOT the system "Coaches" folder
            # Only show coaches folders that are NOT the system folder (exclude name='Coaches' with owner=None)
            coaches_folders = Folder.objects.filter(
                folder_type=Folder.FolderType.COACHES, parent__isnull=True
            )
            root_folders.extend(list(coaches_folders))

            # Coach sees the CONTENTS of their personal folder directly at root
            # Not the folder itself, but what's inside it (Players folder, their documents, etc.)
            # AUTO-RECOVERY: Get or create coach's personal folder
            coach_folder = get_user_personal_folder(user)

            if coach_folder:
                # Get subfolders inside the coach's personal folder
                coach_subfolders = coach_folder.subfolders.select_related("owner").all()
                root_folders.extend(list(coach_subfolders))

        if user.is_player:
            # Player sees the CONTENTS of their personal folder directly at root
            # Not the folder itself, but what's inside it (subfolders and documents)
            # AUTO-RECOVERY: Get or create player's personal folder
            player_folder = get_user_personal_folder(user)

            if player_folder:
                # Get subfolders inside the player's personal folder
                player_subfolders = player_folder.subfolders.select_related(
                    "owner"
                ).all()
                root_folders.extend(list(player_subfolders))

        # By default return only folders. For coaches/players we also surface documents
        result = {"folders": FolderListSerializer(root_folders, many=True).data}

        # If admin, include root-level documents (documents without a folder)
        if user.is_admin:
            admin_root_documents = (
                Document.objects.filter(folder__isnull=True)
                .select_related("owner", "uploaded_by")
                .all()
            )
            if admin_root_documents.exists():
                result["documents"] = DocumentListSerializer(
                    admin_root_documents, many=True
                ).data

        # If coach, include documents directly under their personal folder and the folder ID
        if user.is_coach and coach_folder:
            coach_documents = coach_folder.documents.select_related(
                "owner", "uploaded_by"
            ).all()
            result["documents"] = DocumentListSerializer(
                coach_documents, many=True
            ).data
            result["personal_folder_id"] = (
                coach_folder.id
            )  # Add personal folder ID for uploads/folder creation

        # If player, include documents directly under their personal folder and the folder ID
        if user.is_player and player_folder:
            player_documents = player_folder.documents.select_related(
                "owner", "uploaded_by"
            ).all()
            # Merge with any existing documents key
            if "documents" in result:
                result["documents"].extend(
                    DocumentListSerializer(player_documents, many=True).data
                )
            else:
                result["documents"] = DocumentListSerializer(
                    player_documents, many=True
                ).data
            result["personal_folder_id"] = (
                player_folder.id
            )  # Add personal folder ID for uploads/folder creation

        return Response(result)

    @action(detail=False, methods=["get"])
    def personal_folder(self, request):
        """
        Get the user's personal folder for copy operations.
        Returns the folder ID that non-admin users should copy files to.

        AUTO-RECOVERY: If personal folder is missing, it will be automatically recreated.
        """
        user = request.user

        if user.is_admin:
            return Response(
                {"error": "Admins do not have a specific personal folder"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Use auto-recovery utility
        personal_folder = get_user_personal_folder(user)

        if not personal_folder:
            return Response(
                {"error": "Personal folder not found. Please contact administrator."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "id": personal_folder.id,
                "name": personal_folder.name,
                "folder_type": personal_folder.folder_type,
            }
        )

    @action(detail=False, methods=["get"])
    def search(self, request):
        """
        Search for folders by name and return results with their full path.
        Query parameter: q (search query)
        """
        user = request.user
        query = request.GET.get("q", "").strip()

        if not query:
            return Response({"folders": [], "message": "Please provide a search query"})

        # Get accessible folders based on user role
        if user.is_admin:
            folders = Folder.objects.all()
        else:
            # Build query based on user role
            folder_query = Q(folder_type=Folder.FolderType.PUBLIC)

            if user.is_coach:
                folder_query |= Q(
                    folder_type=Folder.FolderType.COACH_PERSONAL, owner=user
                )
                folder_query |= Q(
                    folder_type=Folder.FolderType.PLAYERS, parent__owner=user
                )
                folder_query |= Q(
                    folder_type=Folder.FolderType.PLAYER_PERSONAL,
                    parent__parent__owner=user,
                )
                folder_query |= Q(folder_type=Folder.FolderType.COACHES)

            if user.is_player:
                folder_query |= Q(
                    folder_type=Folder.FolderType.PLAYER_PERSONAL, owner=user
                )

            folders = Folder.objects.filter(folder_query).distinct()

        # Filter by search query (case-insensitive)
        folders = folders.filter(name__icontains=query).select_related(
            "owner", "parent"
        )

        # Build results with full path
        results = []
        for folder in folders:
            results.append(
                {
                    "id": folder.id,
                    "name": folder.name,
                    "folder_type": folder.folder_type,
                    "location": folder.get_full_path(),
                    "type": "folder",
                }
            )

        return Response({"results": results, "count": len(results)})


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
        if self.action == "list":
            return Document.objects.none()

        # For other actions (retrieve, update, delete), return accessible documents
        if user.is_admin:
            return Document.objects.select_related(
                "folder", "owner", "uploaded_by"
            ).all()

        # Build query based on user role using Q objects (more efficient)
        query = Q(folder__folder_type=Folder.FolderType.PUBLIC)

        if user.is_coach:
            # Coach's own documents
            query |= Q(
                folder__folder_type=Folder.FolderType.COACH_PERSONAL, folder__owner=user
            )
            query |= Q(
                folder__folder_type=Folder.FolderType.PLAYERS,
                folder__parent__owner=user,
            )
            query |= Q(
                folder__folder_type=Folder.FolderType.PLAYER_PERSONAL,
                folder__parent__parent__owner=user,
            )

        if user.is_player:
            # Player's own documents
            query |= Q(
                folder__folder_type=Folder.FolderType.PLAYER_PERSONAL,
                folder__owner=user,
            )

        return (
            Document.objects.select_related("folder", "owner", "uploaded_by")
            .filter(query)
            .distinct()
        )

    def get_serializer_class(self):
        if self.action == "create":
            return DocumentCreateSerializer
        elif self.action == "retrieve":
            return DocumentDetailSerializer
        elif self.action == "copy":
            return DocumentCopySerializer
        return DocumentListSerializer

    def retrieve(self, request, *args, **kwargs):
        document = self.get_object()

        if not document.can_view(request.user):
            return Response(
                {"error": "You don't have permission to view this document"},
                status=status.HTTP_403_FORBIDDEN,
            )

        return super().retrieve(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        document = self.get_object()

        if not document.can_edit(request.user):
            return Response(
                {"error": "You don't have permission to edit this document"},
                status=status.HTTP_403_FORBIDDEN,
            )

        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        document = self.get_object()

        if not document.can_delete(request.user):
            return Response(
                {"error": "You don't have permission to delete this document"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Delete from Cloudinary if stored there
        if document.cloudinary_url and "res.cloudinary.com" in document.cloudinary_url:
            try:
                # Extract Cloudinary public_id from URL
                path = document.cloudinary_url.split("/upload/")[1]
                public_id = "/".join(path.split("/")[1:]).rsplit(".", 1)[0]
                cloudinary.uploader.destroy(public_id, resource_type="raw")
            except Exception as e:
                print(f"⚠️ Cloudinary deletion failed: {e}")

        return super().destroy(request, *args, **kwargs)


    @action(detail=True, methods=["post"])
    def copy(self, request, pk=None):
        """Create a copy of a document in Google Drive and sync to app folder"""
        document = self.get_object()

        if not document.can_view(request.user):
            return Response(
                {"error": "You don't have permission to view this document"},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target_folder = serializer.validated_data["target_folder"]
        token_data = request.data.get("tokens")
        requires_google_copy = bool(document.google_drive_id)
        if requires_google_copy:
            if not token_data or not token_data.get("access_token"):
                return Response({"error": "Google authentication required", "needsAuth": True}, status=status.HTTP_401_UNAUTHORIZED)

        # Google Drive copy logic (similar to google_views.py open_document_in_google_drive)
        from .google_views import get_credentials_from_tokens, get_or_create_app_folder, get_embed_url, MIME_TYPES, normalize_extension
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload
        import requests
        from io import BytesIO

        try:
            # If the document is not linked to Google Drive, perform a local DB copy
            if not requires_google_copy:
                copy = document.create_copy(request.user, target_folder)
                return Response(DocumentDetailSerializer(copy).data, status=status.HTTP_201_CREATED)
            ext = normalize_extension(document.file_extension)
            file_type = 'sheet' if ext in ['xlsx', 'xls'] else 'doc'
            export_mime = MIME_TYPES['xlsx'] if file_type == 'sheet' else MIME_TYPES['docx']
            google_mime = MIME_TYPES['google_sheet'] if file_type == 'sheet' else MIME_TYPES['google_doc']

            export_url = f"https://docs.google.com/{'spreadsheets' if file_type == 'sheet' else 'document'}/d/{document.google_drive_id}/export?format={'xlsx' if file_type == 'sheet' else 'docx'}"
            response = requests.get(export_url, timeout=30)
            if response.status_code != 200:
                raise Exception(f"Export failed with status {response.status_code}")

            file_content = BytesIO(response.content)
            credentials = get_credentials_from_tokens(token_data)
            drive_service = build('drive', 'v3', credentials=credentials)
            app_folder_id = get_or_create_app_folder(drive_service)

            base_title = document.title.rsplit('.', 1)[0] if '.' in document.title else document.title
            copy_name = f"{base_title} (Copy)"
            file_metadata = {
                'name': copy_name,
                'mimeType': google_mime,
            }
            if app_folder_id:
                file_metadata['parents'] = [app_folder_id]

            media = MediaIoBaseUpload(file_content, mimetype=export_mime, resumable=True)
            new_file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, mimeType, webViewLink'
            ).execute()

            # Set admin permissions for non-public folders
            is_public = document.is_in_public_folder()
            if is_public:
                try:
                    drive_service.files().update(
                        fileId=new_file['id'],
                        body={'copyRequiresWriterPermission': False},
                        fields='id'
                    ).execute()
                    drive_service.permissions().create(
                        fileId=new_file['id'],
                        body={'type': 'anyone', 'role': 'writer'},
                        fields='id'
                    ).execute()
                except Exception as perm_error:
                    print(f"Failed to set public edit permissions: {perm_error}")
            else:
                # Share with all admins as writers
                from users.models import User
                admin_users = User.objects.filter(role=User.Role.ADMIN)
                for admin in admin_users:
                    if admin.email:
                        try:
                            drive_service.permissions().create(
                                fileId=new_file['id'],
                                body={
                                    'type': 'user',
                                    'role': 'writer',
                                    'emailAddress': admin.email,
                                },
                                sendNotificationEmail=False,
                                fields='id'
                            ).execute()
                        except Exception as share_error:
                            print(f"Failed to share with admin {admin.email}: {share_error}")

            # Create database record for the copy
            from .folder_utils import get_user_personal_folder
            user_folder = get_user_personal_folder(request.user) if target_folder is None else target_folder
            copy_title_with_ext = f"{copy_name}{document.file_extension}"
            existing_count = Document.objects.filter(folder=user_folder, title__startswith=copy_name).count()
            if existing_count > 0:
                copy_title_with_ext = f"{base_title} (Copy {existing_count + 1}){document.file_extension}"

            db_copy = Document.objects.create(
                title=copy_title_with_ext,
                google_drive_id=new_file['id'],
                file_extension=document.file_extension,
                folder=user_folder,
                uploaded_by=request.user,
                owner=request.user,
                status=Document.DocumentStatus.COPY,
                original_document=document,
                description=f"Copy of {document.title} from Public folder",
            )

            edit_url = get_embed_url(new_file['id'], file_type, edit=True)
            return Response(
                {**DocumentDetailSerializer(db_copy).data, **{
                    'editUrl': edit_url,
                    'webViewLink': new_file.get('webViewLink'),
                    'isCopy': True,
                    'copyId': db_copy.id,
                    'originalGoogleFileId': document.google_drive_id,
                }},
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["patch"])
    def move(self, request, pk=None):
        """Move a document to a different folder"""
        document = self.get_object()

        if not document.can_edit(request.user):
            return Response(
                {"error": "You don't have permission to move this document"},
                status=status.HTTP_403_FORBIDDEN,
            )

        target_folder_id = request.data.get("target_folder")
        
        # target_folder can be null for moving to root (admin only) or needs to be resolved for coach/player
        if target_folder_id is None:
            # Moving to root level
            if request.user.is_admin:
                # Admin can move to root (null folder)
                document.folder = None
                document.save()
                
                return Response(
                    DocumentDetailSerializer(document, context={'request': request}).data,
                    status=status.HTTP_200_OK
                )
            elif request.user.is_coach or request.user.is_player:
                # Coach/Player should move to their personal folder
                from .models import Folder
                try:
                    # Get user's personal folder
                    if request.user.is_coach:
                        personal_folder = Folder.objects.filter(
                            folder_type=Folder.FolderType.COACH_PERSONAL,
                            owner=request.user
                        ).first()
                    else:  # is_player
                        personal_folder = Folder.objects.filter(
                            folder_type=Folder.FolderType.PLAYER_PERSONAL,
                            owner=request.user
                        ).first()
                    
                    if not personal_folder:
                        return Response(
                            {"error": "Your personal folder could not be found"},
                            status=status.HTTP_404_NOT_FOUND,
                        )
                    
                    # Move to personal folder
                    document.folder = personal_folder
                    document.save()
                    
                    return Response(
                        DocumentDetailSerializer(document, context={'request': request}).data,
                        status=status.HTTP_200_OK
                    )
                except Exception as e:
                    return Response(
                        {"error": f"Error finding personal folder: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
            else:
                return Response(
                    {"error": "You don't have permission to move files to root level"},
                    status=status.HTTP_403_FORBIDDEN,
                )

        try:
            from .models import Folder
            target_folder = Folder.objects.get(pk=target_folder_id)
            
            # Check if user has permission to add to target folder
            if not target_folder.can_edit(request.user):
                return Response(
                    {"error": "You don't have permission to add files to this folder"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            
            # Move the document
            document.folder = target_folder
            document.save()
            
            return Response(
                DocumentDetailSerializer(document, context={'request': request}).data,
                status=status.HTTP_200_OK
            )
        except Folder.DoesNotExist:
            return Response(
                {"error": "Target folder not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["patch"])
    def rename(self, request, pk=None):
        """Rename a document - only updates the title in database, not the physical file"""
        document = self.get_object()

        if not document.can_edit(request.user):
            return Response(
                {"error": "You don't have permission to rename this document"},
                status=status.HTTP_403_FORBIDDEN,
            )

        new_title = request.data.get("title")
        if not new_title:
            return Response(
                {"error": "New title is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Update the title in database
        # Note: We're only updating the display title, not renaming the physical file in storage
        # This is safer and faster, and the physical filename doesn't need to match the title
        document.title = new_title
        document.save()

        return Response(
            DocumentDetailSerializer(document).data, status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["get"])
    def copies(self, request, pk=None):
        """Get all copies of a document"""
        document = self.get_object()

        if not document.can_view(request.user):
            return Response(
                {"error": "You don't have permission to view this document"},
                status=status.HTTP_403_FORBIDDEN,
            )

        copies = document.copies.all()
        return Response(DocumentListSerializer(copies, many=True).data)

    @action(detail=False, methods=["get"])
    def my_documents(self, request):
        """Get documents owned by the current user"""
        documents = Document.objects.filter(owner=request.user)
        return Response(DocumentListSerializer(documents, many=True).data)

    @action(detail=False, methods=["get"])
    def search(self, request):
        """
        Search for documents by title and return results with their folder location.
        Query parameter: q (search query)
        """
        user = request.user
        query = request.GET.get("q", "").strip()

        if not query:
            return Response(
                {"documents": [], "message": "Please provide a search query"}
            )

        # Get accessible documents based on user role
        if user.is_admin:
            documents = Document.objects.select_related(
                "folder", "owner", "uploaded_by"
            ).all()
        else:
            # Build query based on user role
            doc_query = Q(folder__folder_type=Folder.FolderType.PUBLIC)

            if user.is_coach:
                doc_query |= Q(
                    folder__folder_type=Folder.FolderType.COACH_PERSONAL,
                    folder__owner=user,
                )
                doc_query |= Q(
                    folder__folder_type=Folder.FolderType.PLAYERS,
                    folder__parent__owner=user,
                )
                doc_query |= Q(
                    folder__folder_type=Folder.FolderType.PLAYER_PERSONAL,
                    folder__parent__parent__owner=user,
                )

            if user.is_player:
                doc_query |= Q(
                    folder__folder_type=Folder.FolderType.PLAYER_PERSONAL,
                    folder__owner=user,
                )

            documents = (
                Document.objects.select_related("folder", "owner", "uploaded_by")
                .filter(doc_query)
                .distinct()
            )

        # Filter by search query (case-insensitive)
        documents = documents.filter(title__icontains=query)

        # Build results with folder location
        results = []
        for doc in documents:
            results.append(
                {
                    "id": doc.id,
                    "title": doc.title,
                    "file_extension": doc.file_extension,
                    "folder_id": doc.folder.id,
                    "folder_name": doc.folder.name,
                    "location": doc.folder.get_full_path(),
                    "uploaded_at": doc.uploaded_at,
                    "uploaded_by": (
                        doc.uploaded_by.get_full_name() if doc.uploaded_by else None
                    ),
                    "type": "document",
                }
            )

        return Response({"results": results, "count": len(results)})


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
        return DocumentPermission.objects.filter(Q(document__owner=user) | Q(user=user))

    def perform_create(self, serializer):
        document = serializer.validated_data["document"]

        # Only document owner or admin can grant permissions
        if not (self.request.user.is_admin or document.owner == self.request.user):
            raise permissions.PermissionDenied(
                "Only document owner or admin can grant permissions"
            )

        serializer.save(granted_by=self.request.user)
