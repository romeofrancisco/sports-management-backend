from django.db.models.signals import post_save, post_migrate, pre_delete, pre_save
from django.dispatch import receiver
from django.apps import apps
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from teams.models import Coach, Player, Team
from users.models import User
from .models import Folder, Document
import threading

# Thread-local storage to track when we're in a CASCADE deletion
_thread_locals = threading.local()

def set_cascade_deletion_active(active=True):
    """Set flag to indicate CASCADE deletion is in progress"""
    _thread_locals.cascade_deletion_active = active

def is_cascade_deletion_active():
    """Check if CASCADE deletion is in progress"""
    return getattr(_thread_locals, 'cascade_deletion_active', False)


# ============== User Name Change - Update Folder Name ==============

@receiver(pre_save, sender=User)
def track_user_name_change(sender, instance, **kwargs):
    """Track the old name before saving to detect changes"""
    if instance.pk:  # Only for existing users
        try:
            old_instance = User.objects.get(pk=instance.pk)
            instance._old_first_name = old_instance.first_name
            instance._old_last_name = old_instance.last_name
            instance._old_full_name = old_instance.get_full_name()
        except User.DoesNotExist:
            instance._old_first_name = None
            instance._old_last_name = None
            instance._old_full_name = None
    else:
        instance._old_first_name = None
        instance._old_last_name = None
        instance._old_full_name = None


@receiver(post_save, sender=User)
def update_folder_name_on_user_name_change(sender, instance, created, **kwargs):
    """
    When a user's name changes, update their folder name to match.
    This applies to both coaches and players.
    """
    if created:
        return  # Skip for new users - folders haven't been created yet
    
    # Check if name actually changed
    old_full_name = getattr(instance, '_old_full_name', None)
    new_full_name = instance.get_full_name()
    
    if old_full_name == new_full_name:
        return  # Name hasn't changed, nothing to do
    
    # Find user's personal folder and update name
    if instance.is_coach:
        # Update coach's personal folder
        folder = Folder.objects.filter(
            folder_type=Folder.FolderType.COACH_PERSONAL,
            owner=instance
        ).first()
    elif instance.is_player:
        # Update player's personal folder
        folder = Folder.objects.filter(
            folder_type=Folder.FolderType.PLAYER_PERSONAL,
            owner=instance
        ).first()
    else:
        folder = None
    
    if folder:
        # Check for name conflicts in the same parent
        folder_name = new_full_name
        counter = 2
        while Folder.objects.filter(name=folder_name, parent=folder.parent).exclude(pk=folder.pk).exists():
            folder_name = f"{new_full_name} ({counter})"
            counter += 1
        
        folder.name = folder_name
        folder.save(update_fields=['name'])
        print(f"✓ Updated folder name from '{old_full_name}' to '{folder_name}'")


# ============== Root Folders Creation ==============


@receiver(post_migrate)
def create_root_folders(sender, **kwargs):
    """
    Create root folders (Public, Coaches) after migrations.
    This ensures these folders exist before any coaches or players are created.
    """
    # Only run for the documents app
    if sender.name != 'documents':
        return
    
    # Create Public folder
    public_folder, created = Folder.objects.get_or_create(
        name='Public',
        folder_type=Folder.FolderType.PUBLIC,
        parent=None,
        defaults={'owner': None}
    )
    if created:
        print("✓ Created Public root folder")
    
    # Create Coaches folder (tolerant of an existing folder with wrong type)
    coaches_folder = Folder.objects.filter(name='Coaches', parent=None).first()
    if coaches_folder:
        # Normalize folder_type if needed
        if coaches_folder.folder_type != Folder.FolderType.COACHES:
            coaches_folder.folder_type = Folder.FolderType.COACHES
            coaches_folder.save(update_fields=['folder_type'])
    else:
        coaches_folder, created = Folder.objects.get_or_create(
            name='Coaches',
            folder_type=Folder.FolderType.COACHES,
            parent=None,
            defaults={'owner': None}
        )
        if created:
            print("✓ Created Coaches root folder")


@receiver(post_save, sender=Coach)
def create_coach_folder(sender, instance, created, **kwargs):
    """
    Automatically create a personal folder for a coach when they are created.
    The folder is created inside the Coaches folder.
    """
    if created:
        # Get the Coaches root folder (tolerate older incorrect folder_type)
        coaches_folder = Folder.objects.filter(name='Coaches', parent=None).first()
        if not coaches_folder:
            coaches_folder, _ = Folder.objects.get_or_create(
                name='Coaches',
                folder_type=Folder.FolderType.COACHES,
                parent=None,
                defaults={'owner': None}
            )
        else:
            # Normalize folder_type if needed
            if coaches_folder.folder_type != Folder.FolderType.COACHES:
                coaches_folder.folder_type = Folder.FolderType.COACHES
                coaches_folder.save(update_fields=['folder_type'])
        
        # Create personal folder for the coach
        coach_folder, folder_created = Folder.objects.get_or_create(
            name=f"{instance.user.get_full_name()}",
            folder_type=Folder.FolderType.COACH_PERSONAL,
            parent=coaches_folder,
            owner=instance.user
        )
        
        if folder_created:
            # Create Players subfolder inside coach's personal folder
            Folder.objects.get_or_create(
                name='Players',
                folder_type=Folder.FolderType.PLAYERS,
                parent=coach_folder,
                owner=instance.user
            )
            print(f"✓ Created folder structure for coach: {instance.user.get_full_name()}")


@receiver(post_save, sender=Player)
def create_player_folder(sender, instance, created, **kwargs):
    """
    Automatically create a personal folder for a player when they are created.
    
    Logic:
    1. If player has a team with a coach, create folder inside that coach's Players folder
    2. If no team/coach, create a standalone player folder
    """
    if created:
        player_name = instance.user.get_full_name()
        
        # Check if player has a team with a coach
        if instance.team and instance.team.head_coach:
            coach = instance.team.head_coach
            
            # Find the coach's personal folder
            coach_folder = Folder.objects.filter(
                folder_type=Folder.FolderType.COACH_PERSONAL,
                owner=coach.user
            ).first()
            
            if coach_folder:
                # Find or create the Players folder inside coach's folder
                players_folder, _ = Folder.objects.get_or_create(
                    name='Players',
                    folder_type=Folder.FolderType.PLAYERS,
                    parent=coach_folder,
                    owner=coach.user
                )
                
                # Create player's personal folder inside the Players folder
                player_folder, folder_created = Folder.objects.get_or_create(
                    name=player_name,
                    folder_type=Folder.FolderType.PLAYER_PERSONAL,
                    parent=players_folder,
                    owner=instance.user
                )
                
                if folder_created:
                    print(f"✓ Created folder for player {player_name} under coach {coach.user.get_full_name()}")
            else:
                # Coach folder doesn't exist, create standalone player folder
                _create_standalone_player_folder(instance, player_name)
        else:
            # No team or coach, create standalone player folder
            _create_standalone_player_folder(instance, player_name)


def _create_standalone_player_folder(player_instance, player_name):
    """Helper function to create a standalone player folder"""
    player_folder, folder_created = Folder.objects.get_or_create(
        name=player_name,
        folder_type=Folder.FolderType.PLAYER_PERSONAL,
        parent=None,
        owner=player_instance.user
    )
    
    if folder_created:
        print(f"✓ Created standalone folder for player: {player_name}")


@receiver(pre_save, sender=Player)
def track_player_team_change(sender, instance, **kwargs):
    """Track the old team before saving to detect changes"""
    if instance.pk:  # Only for existing players
        try:
            old_instance = Player.objects.get(pk=instance.pk)
            instance._old_team_id = old_instance.team_id
        except Player.DoesNotExist:
            instance._old_team_id = None
    else:
        instance._old_team_id = None


@receiver(post_save, sender=Player)
def update_player_folder_on_team_change(sender, instance, created, **kwargs):
    """
    When a player's team changes, move their folder to the appropriate location:
    - If player has a coach: move to coach's Players folder
    - If player has no coach: move to root as standalone folder
    """
    if created:
        return  # Skip for new players - they'll get folders created in create_player_folder
    
    # Check if team actually changed
    old_team_id = getattr(instance, '_old_team_id', None)
    if old_team_id == instance.team_id:
        return  # Team hasn't changed, nothing to do
    
    # Team has changed, reorganize folder
    _move_player_folder(instance)


@receiver(pre_save, sender=Team)
def track_team_coach_change(sender, instance, **kwargs):
    """Track the old head_coach before saving to detect changes"""
    if instance.pk:  # Only for existing teams
        try:
            old_instance = Team.objects.get(pk=instance.pk)
            instance._old_head_coach_id = old_instance.head_coach_id
        except Team.DoesNotExist:
            instance._old_head_coach_id = None
    else:
        instance._old_head_coach_id = None


@receiver(post_save, sender=Team)
def update_players_folders_on_coach_change(sender, instance, created, **kwargs):
    """
    When a team's head_coach changes, move all player folders in that team
    to the appropriate location (under new coach or to root if no coach)
    """
    if created:
        return  # Skip for new teams
    
    # Check if coach actually changed
    old_coach_id = getattr(instance, '_old_head_coach_id', None)
    if old_coach_id == instance.head_coach_id:
        return  # Coach hasn't changed, nothing to do
    
    # Coach has changed, reorganize all player folders in this team
    players = Player.objects.filter(team=instance)
    for player in players:
        _move_player_folder(player)



def _move_player_folder(player):
    """
    Helper function to move a player's folder to the correct location
    based on their current team and coach.
    """
    player_name = player.user.get_full_name()
    
    # Find existing player folder
    existing_folder = Folder.objects.filter(
        folder_type=Folder.FolderType.PLAYER_PERSONAL,
        owner=player.user
    ).first()
    
    if not existing_folder:
        return  # No folder to move
    
    # Determine target parent based on team/coach
    target_parent = None
    coach = None
    
    if player.team and player.team.head_coach:
        # Player has a coach - move under coach's Players folder
        coach = player.team.head_coach
        
        # Find or create coach's folder structure
        coach_folder = Folder.objects.filter(
            folder_type=Folder.FolderType.COACH_PERSONAL,
            owner=coach.user
        ).first()
        
        if coach_folder:
            players_folder, _ = Folder.objects.get_or_create(
                name='Players',
                folder_type=Folder.FolderType.PLAYERS,
                parent=coach_folder,
                owner=coach.user
            )
            target_parent = players_folder
    else:
        # Player has no coach - move to root
        target_parent = None
    
    # Only move if parent actually changed
    if existing_folder.parent != target_parent:
        # Check for name conflicts in target location
        folder_name = player_name
        counter = 2
        while Folder.objects.filter(name=folder_name, parent=target_parent).exclude(pk=existing_folder.pk).exists():
            folder_name = f"{player_name} {counter}"
            counter += 1
        
        # Update folder name if it changed to avoid conflict
        if folder_name != existing_folder.name:
            existing_folder.name = folder_name
        
        # Move the folder
        existing_folder.parent = target_parent
        existing_folder.save(update_fields=['parent', 'name'])
        
        if target_parent:
            print(f"✓ Moved folder for player {player_name} to coach {coach.user.get_full_name()}'s folder")
        else:
            print(f"✓ Moved folder for player {player_name} to root (no coach)")




@receiver(pre_delete, sender=User)
def set_user_cascade_flag(sender, instance, **kwargs):
    """Mark that we're in a CASCADE deletion when deleting a user"""
    set_cascade_deletion_active(True)


@receiver(pre_delete, sender=Player)
def set_player_cascade_flag(sender, instance, **kwargs):
    """Mark that we're in a CASCADE deletion when deleting a player"""
    set_cascade_deletion_active(True)


@receiver(pre_delete, sender=Coach)
def set_coach_cascade_flag(sender, instance, **kwargs):
    """Mark that we're in a CASCADE deletion when deleting a coach"""
    set_cascade_deletion_active(True)


@receiver(pre_delete, sender=Folder)
def prevent_critical_folder_deletion(sender, instance, **kwargs):
    """
    Prevent deletion of critical system folders only.
    This protects against accidental deletion of important folder structures.
    
    Protected folders:
    - THE system-created root folders (Public, Coaches) with specific names and no owner
    - System-created personal folders (direct children of Coaches or Players folder)
    
    User-created subfolders within personal folders CAN be deleted.
    Admin-created additional folders with same types CAN be deleted.
    
    EXCEPTION: Allow deletion during CASCADE operations (user/player/coach deletion).
    """
    # Allow all deletions during CASCADE (user/player/coach deletion)
    if is_cascade_deletion_active():
        return
    
    # Protect ONLY THE system root folders (by name and no owner)
    # Admin-created folders with same types but different names can be deleted
    if instance.parent is None:
        # Protect THE "Public" root folder
        if (instance.folder_type == Folder.FolderType.PUBLIC and 
            instance.name == 'Public' and 
            instance.owner is None):
            raise PermissionDenied(
                f"Cannot delete the system 'Public' folder. "
                f"This is a protected system folder."
            )
        
        # Protect THE "Coaches" root folder
        if (instance.folder_type == Folder.FolderType.COACHES and 
            instance.name == 'Coaches' and 
            instance.owner is None):
            raise PermissionDenied(
                f"Cannot delete the system 'Coaches' folder. "
                f"This is a protected system folder."
            )
    
    # Coach personal folders (direct children of Coaches folder)
    if (instance.folder_type == Folder.FolderType.COACH_PERSONAL and 
        instance.parent and 
        instance.parent.name == 'Coaches'):
        raise PermissionDenied(
            f"Cannot delete coach personal folder '{instance.name}'. "
            f"This is a protected system folder."
        )
    
    # Players folders (direct children of coach personal folders)
    if (instance.folder_type == Folder.FolderType.PLAYERS and 
        instance.parent and 
        instance.parent.folder_type == Folder.FolderType.COACH_PERSONAL):
        raise PermissionDenied(
            f"Cannot delete Players folder '{instance.name}'. "
            f"This is a protected system folder."
        )
    
    # Player personal folders (direct children of Players folder)
    if (instance.folder_type == Folder.FolderType.PLAYER_PERSONAL and 
        instance.parent and 
        instance.parent.folder_type == Folder.FolderType.PLAYERS):
        raise PermissionDenied(
            f"Cannot delete player personal folder '{instance.name}'. "
            f"This is a protected system folder."
        )
    
    # All other folders (user-created subfolders) can be deleted


# ============== Player Registration Document Sync Signals ==============

@receiver(pre_delete, sender=Player)
def cleanup_registration_documents_on_player_delete(sender, instance, **kwargs):
    """
    When a player is deleted, also delete their synced registration documents.
    This ensures the registration documents are cleaned up when the player is removed.
    """
    from teams.models import PlayerRegistration, PlayerRegistrationDocument
    
    # Find the registration associated with this player
    try:
        registration = PlayerRegistration.objects.get(approved_player=instance)
        
        # Delete synced documents in the Documents app
        for reg_doc in registration.documents.all():
            if reg_doc.synced_document:
                try:
                    # Delete the synced document
                    synced_doc = reg_doc.synced_document
                    reg_doc.synced_document = None
                    reg_doc.save(update_fields=['synced_document'])
                    synced_doc.delete()
                except Exception as e:
                    print(f"Error deleting synced document: {e}")
    except PlayerRegistration.DoesNotExist:
        pass  # Player was created without registration (legacy)


@receiver(pre_delete, sender=Document)
def sync_document_deletion_to_registration(sender, instance, **kwargs):
    """
    When a synced document is deleted from the Documents app,
    update the registration document to clear the synced_document reference.
    """
    from teams.models import PlayerRegistrationDocument
    
    # Check if this document is linked to a registration document
    try:
        reg_doc = PlayerRegistrationDocument.objects.get(synced_document=instance)
        reg_doc.synced_document = None
        reg_doc.save(update_fields=['synced_document'])
    except PlayerRegistrationDocument.DoesNotExist:
        pass  # Not a registration document
