"""
Utility functions for ensuring folder integrity and auto-recovery.
"""
from .models import Folder
from teams.models import Coach, Player


def ensure_coach_folder_structure(coach):
    """
    Ensure a coach has their complete folder structure.
    Creates missing folders if they don't exist.
    
    Returns: (coach_folder, players_folder, created)
    """
    # Get or create the Coaches root folder
    # Be tolerant of an existing Coaches folder with an older/incorrect folder_type
    coaches_folder = Folder.objects.filter(name='Coaches', parent=None).first()
    if coaches_folder:
        # If an existing folder has a different type, normalize it to COACHES
        if coaches_folder.folder_type != Folder.FolderType.COACHES:
            coaches_folder.folder_type = Folder.FolderType.COACHES
            coaches_folder.save(update_fields=['folder_type'])
    else:
        coaches_folder, _ = Folder.objects.get_or_create(
            name='Coaches',
            folder_type=Folder.FolderType.COACHES,
            parent=None,
            defaults={'owner': None}
        )
    
    # Check if coach already has a folder (by owner)
    existing_coach_folder = Folder.objects.filter(
        folder_type=Folder.FolderType.COACH_PERSONAL,
        owner=coach.user
    ).first()
    
    if existing_coach_folder:
        # Update folder name if it doesn't match current name
        current_name = coach.user.get_full_name()
        if existing_coach_folder.name != current_name:
            # Check for conflicts
            folder_name = current_name
            counter = 2
            while Folder.objects.filter(name=folder_name, parent=coaches_folder).exclude(pk=existing_coach_folder.pk).exists():
                folder_name = f"{current_name} ({counter})"
                counter += 1
            existing_coach_folder.name = folder_name
            existing_coach_folder.save(update_fields=['name'])
        
        # Ensure Players subfolder exists
        players_folder, players_created = Folder.objects.get_or_create(
            name='Players',
            folder_type=Folder.FolderType.PLAYERS,
            parent=existing_coach_folder,
            owner=coach.user
        )
        
        return existing_coach_folder, players_folder, players_created
    
    # Create new personal folder for the coach
    folder_name = coach.user.get_full_name()
    counter = 2
    while Folder.objects.filter(name=folder_name, parent=coaches_folder).exists():
        folder_name = f"{coach.user.get_full_name()} ({counter})"
        counter += 1
    
    coach_folder = Folder.objects.create(
        name=folder_name,
        folder_type=Folder.FolderType.COACH_PERSONAL,
        parent=coaches_folder,
        owner=coach.user
    )
    
    # Create Players subfolder inside coach's personal folder
    players_folder = Folder.objects.create(
        name='Players',
        folder_type=Folder.FolderType.PLAYERS,
        parent=coach_folder,
        owner=coach.user
    )
    
    print(f"✓ Restored folder structure for coach: {coach.user.get_full_name()}")
    
    return coach_folder, players_folder, True


def ensure_player_folder_structure(player):
    """
    Ensure a player has their personal folder.
    Creates missing folder if it doesn't exist.
    Handles duplicate names by appending email or counter.
    Also updates folder name if player's name has changed.
    
    Returns: (player_folder, created)
    """
    player_name = player.user.get_full_name()
    
    # Check if player already has a folder (by owner)
    existing_folder = Folder.objects.filter(
        folder_type=Folder.FolderType.PLAYER_PERSONAL,
        owner=player.user
    ).first()
    
    # Check if player has a team with a coach
    if player.team and player.team.head_coach:
        coach = player.team.head_coach
        
        # Ensure coach folder structure exists first
        coach_folder, players_folder, _ = ensure_coach_folder_structure(coach)
        
        if existing_folder:
            # Update folder name if it doesn't match current name
            if existing_folder.name != player_name:
                folder_name = player_name
                counter = 2
                while Folder.objects.filter(name=folder_name, parent=existing_folder.parent).exclude(pk=existing_folder.pk).exists():
                    folder_name = f"{player_name} ({counter})"
                    counter += 1
                existing_folder.name = folder_name
                existing_folder.save(update_fields=['name'])
            
            # Move folder if it's not already under the correct coach
            if existing_folder.parent != players_folder:
                # Check for name conflicts in new location
                folder_name = existing_folder.name
                counter = 2
                while Folder.objects.filter(name=folder_name, parent=players_folder).exclude(pk=existing_folder.pk).exists():
                    folder_name = f"{player_name} ({counter})"
                    counter += 1
                existing_folder.name = folder_name
                existing_folder.parent = players_folder
                existing_folder.save(update_fields=['name', 'parent'])
                print(f"✓ Moved folder for player {player_name} to coach {coach.user.get_full_name()}'s folder")
            
            return existing_folder, False
        
        # Create unique folder name to avoid conflicts
        folder_name = player_name
        counter = 2
        while Folder.objects.filter(name=folder_name, parent=players_folder).exists():
            folder_name = f"{player_name} ({counter})"
            counter += 1
        
        # Create player's personal folder inside the Players folder
        player_folder = Folder.objects.create(
            name=folder_name,
            folder_type=Folder.FolderType.PLAYER_PERSONAL,
            parent=players_folder,
            owner=player.user
        )
        
        print(f"✓ Restored folder for player {player_name} under coach {coach.user.get_full_name()}")
        return player_folder, True
    else:
        # No team or coach
        if existing_folder:
            # Update folder name if it doesn't match current name
            if existing_folder.name != player_name:
                folder_name = player_name
                counter = 2
                while Folder.objects.filter(name=folder_name, parent=None).exclude(pk=existing_folder.pk).exists():
                    folder_name = f"{player_name} ({counter})"
                    counter += 1
                existing_folder.name = folder_name
                existing_folder.save(update_fields=['name'])
            
            # Move to root if not already there
            if existing_folder.parent is not None:
                existing_folder.parent = None
                existing_folder.save(update_fields=['parent'])
                print(f"✓ Moved folder for player {player_name} to root (no coach)")
            
            return existing_folder, False
        
        # Create standalone player folder
        folder_name = player_name
        counter = 2
        while Folder.objects.filter(name=folder_name, parent=None).exists():
            folder_name = f"{player_name} ({counter})"
            counter += 1
        
        player_folder = Folder.objects.create(
            name=folder_name,
            folder_type=Folder.FolderType.PLAYER_PERSONAL,
            parent=None,
            owner=player.user
        )
        
        print(f"✓ Restored standalone folder for player: {player_name}")
        return player_folder, True


def ensure_root_folders():
    """
    Ensure all root folders (Public, Coaches) exist.
    
    Returns: dict with folder objects
    """
    # Create Public folder
    public_folder, public_created = Folder.objects.get_or_create(
        name='Public',
        folder_type=Folder.FolderType.PUBLIC,
        parent=None,
        defaults={'owner': None}
    )
    
    # Create Coaches folder
    coaches_folder, coaches_created = Folder.objects.get_or_create(
        name='Coaches',
        folder_type=Folder.FolderType.COACHES,
        parent=None,
        defaults={'owner': None}
    )
    
    if public_created:
        print("✓ Restored Public root folder")
    
    if coaches_created:
        print("✓ Restored Coaches root folder")
    
    return {
        'public': public_folder,
        'coaches': coaches_folder,
        'created': public_created or coaches_created
    }


def recover_all_user_folders():
    """
    Recover folder structures for all coaches and players.
    Useful for bulk recovery after accidental deletions.
    
    Returns: dict with recovery statistics
    """
    stats = {
        'root_folders_created': 0,
        'coach_folders_created': 0,
        'player_folders_created': 0,
        'total_created': 0
    }
    
    # Ensure root folders exist
    root_result = ensure_root_folders()
    if root_result['created']:
        stats['root_folders_created'] += 1
    
    # Recover all coach folders
    coaches = Coach.objects.select_related('user').all()
    for coach in coaches:
        _, _, created = ensure_coach_folder_structure(coach)
        if created:
            stats['coach_folders_created'] += 1
    
    # Recover all player folders
    players = Player.objects.select_related('user', 'team__head_coach__user').all()
    for player in players:
        _, created = ensure_player_folder_structure(player)
        if created:
            stats['player_folders_created'] += 1
    
    stats['total_created'] = (
        stats['root_folders_created'] + 
        stats['coach_folders_created'] + 
        stats['player_folders_created']
    )
    
    return stats


def get_user_personal_folder(user):
    """
    Get or create a user's personal folder based on their role.
    Automatically recovers missing folders.
    
    Returns: Folder object or None
    """
    if user.is_admin:
        return None
    
    if user.is_coach:
        try:
            coach = Coach.objects.get(user=user)
            coach_folder, _, _ = ensure_coach_folder_structure(coach)
            return coach_folder
        except Coach.DoesNotExist:
            return None
    
    elif user.is_player:
        try:
            player = Player.objects.get(user=user)
            player_folder, _ = ensure_player_folder_structure(player)
            return player_folder
        except Player.DoesNotExist:
            return None
    
    return None
