from django.db.models.signals import post_save, post_migrate
from django.dispatch import receiver
from django.apps import apps
from teams.models import Coach, Player
from .models import Folder


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
    
    # Create Coaches folder
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
        # Get or create the Coaches root folder
        coaches_folder, _ = Folder.objects.get_or_create(
            name='Coaches',
            folder_type=Folder.FolderType.COACHES,
            parent=None,
            defaults={'owner': None}
        )
        
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


@receiver(post_save, sender=Player)
def update_player_folder_on_team_change(sender, instance, created, **kwargs):
    """
    When a player's team changes, move their folder to the new coach's Players folder.
    This runs after the player is saved (not just created).
    """
    if not created and instance.team:  # Only for updates, not creation
        # Check if the player has a coach now
        if instance.team.head_coach:
            coach = instance.team.head_coach
            player_name = instance.user.get_full_name()
            
            # Find existing player folder
            existing_folder = Folder.objects.filter(
                folder_type=Folder.FolderType.PLAYER_PERSONAL,
                owner=instance.user
            ).first()
            
            if existing_folder:
                # Find the coach's Players folder
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
                    
                    # Move player folder under coach's Players folder if not already there
                    if existing_folder.parent != players_folder:
                        existing_folder.parent = players_folder
                        existing_folder.save(update_fields=['parent'])
                        print(f"✓ Moved folder for player {player_name} to coach {coach.user.get_full_name()}'s folder")
