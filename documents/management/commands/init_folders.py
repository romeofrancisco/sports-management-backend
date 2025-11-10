from django.core.management.base import BaseCommand
from django.db.models import Q
from documents.models import Folder
from users.models import User


class Command(BaseCommand):
    help = 'Initialize the document folder structure'

    def handle(self, *args, **options):
        self.stdout.write('Initializing folder structure...')
        
        # Create Public folder (root)
        public_folder, created = Folder.objects.get_or_create(
            name='Public',
            folder_type=Folder.FolderType.PUBLIC,
            parent=None,
            defaults={'owner': None}
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Created Public folder'))
        else:
            self.stdout.write(self.style.WARNING(f'Public folder already exists'))
        
        # Create Coaches folder (root)
        coaches_folder, created = Folder.objects.get_or_create(
            name='Coaches',
            folder_type=Folder.FolderType.COACHES,
            parent=None,
            defaults={'owner': None}
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Created Coaches folder'))
        else:
            self.stdout.write(self.style.WARNING(f'Coaches folder already exists'))
        
        # Create personal folders for all coaches
        coaches = User.objects.filter(role=User.Role.COACH)
        coach_count = 0
        for coach in coaches:
            coach_folder, created = Folder.objects.get_or_create(
                name=f"{coach.get_full_name()}",
                folder_type=Folder.FolderType.COACH_PERSONAL,
                parent=coaches_folder,
                owner=coach
            )
            if created:
                coach_count += 1
                self.stdout.write(self.style.SUCCESS(f'  ✓ Created folder for coach: {coach.get_full_name()}'))
            
            # Create Players subfolder for each coach
            players_folder, _ = Folder.objects.get_or_create(
                name='Players',
                folder_type=Folder.FolderType.PLAYERS,
                parent=coach_folder,
                owner=coach
            )
            
            # Get players from teams where this coach is head coach or assistant coach
            from teams.models import Team, Player
            
            # Get teams coached by this coach
            coached_teams = Team.objects.filter(
                Q(head_coach__user=coach) | Q(assistant_coach__user=coach)
            )
            
            # Get all players from these teams
            player_users = User.objects.filter(
                role=User.Role.PLAYER,
                player_profile__team__in=coached_teams
            ).distinct()
            
            player_folder_count = 0
            for player in player_users:
                # First check if player already has a folder (by owner)
                existing_folder = Folder.objects.filter(
                    folder_type=Folder.FolderType.PLAYER_PERSONAL,
                    parent=players_folder,
                    owner=player
                ).first()
                
                if existing_folder:
                    continue  # Skip if folder already exists
                
                # Create unique folder name to avoid conflicts
                player_name = player.get_full_name()
                folder_name = player_name
                
                # Check if a folder with this name already exists
                counter = 2
                while Folder.objects.filter(name=folder_name, parent=players_folder).exists():
                    folder_name = f"{player_name} {counter}"
                    counter += 1
                
                # Create the folder with unique name
                try:
                    player_folder = Folder.objects.create(
                        name=folder_name,
                        folder_type=Folder.FolderType.PLAYER_PERSONAL,
                        parent=players_folder,
                        owner=player
                    )
                    player_folder_count += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'    Error creating folder for {player_name}: {e}'))
                    continue
            
            if player_folder_count > 0:
                self.stdout.write(self.style.SUCCESS(f'    ✓ Created {player_folder_count} player folders for {coach.get_full_name()}'))
            elif player_users.count() == 0:
                self.stdout.write(self.style.WARNING(f'    No players assigned to teams coached by {coach.get_full_name()}'))
        
        if coach_count > 0:
            self.stdout.write(self.style.SUCCESS(f'✓ Created {coach_count} coach folders'))
        else:
            self.stdout.write(self.style.WARNING(f'No new coach folders created'))
        
        # Create personal folders for players (outside coach structure)
        players = User.objects.filter(role=User.Role.PLAYER)
        player_count = 0
        for player in players:
            # Check if player already has a folder
            existing = Folder.objects.filter(
                folder_type=Folder.FolderType.PLAYER_PERSONAL,
                owner=player
            ).exists()
            
            if not existing:
                # Create unique folder name for standalone player folder
                player_name = player.get_full_name()
                folder_name = player_name
                
                # Check if name exists at root level
                counter = 2
                while Folder.objects.filter(name=folder_name, parent=None).exists():
                    folder_name = f"{player_name} {counter}"
                    counter += 1
                
                # Create standalone player folder
                try:
                    player_folder = Folder.objects.create(
                        name=folder_name,
                        folder_type=Folder.FolderType.PLAYER_PERSONAL,
                        parent=None,
                        owner=player
                    )
                    player_count += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Error creating standalone folder for {player_name}: {e}'))
                    continue
        
        if player_count > 0:
            self.stdout.write(self.style.SUCCESS(f'✓ Created {player_count} standalone player folders'))
        
        self.stdout.write(self.style.SUCCESS('\n✓ Folder structure initialized successfully!'))
        self.stdout.write('\nFolder structure:')
        self.stdout.write('├── Public (Admin uploads only, all can view/copy)')
        self.stdout.write('├── Coaches')
        self.stdout.write('│   ├── [Coach Name 1]')
        self.stdout.write('│   │   ├── [Coach files]')
        self.stdout.write('│   │   └── Players')
        self.stdout.write('│   │       ├── [Player Name 1]')
        self.stdout.write('│   │       └── [Player Name 2]')
        self.stdout.write('│   └── [Coach Name 2]')
        self.stdout.write('└── [Individual Player Folders]')
