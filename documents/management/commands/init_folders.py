from django.core.management.base import BaseCommand
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
                
                # Create personal folders for coach's players
                # You can customize this logic based on your team/player assignment
                players = User.objects.filter(role=User.Role.PLAYER)
                for player in players:
                    player_folder, _ = Folder.objects.get_or_create(
                        name=f"{player.get_full_name()}",
                        folder_type=Folder.FolderType.PLAYER_PERSONAL,
                        parent=players_folder,
                        owner=player
                    )
        
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
                # Create standalone player folder if not already in a coach's structure
                player_folder, created = Folder.objects.get_or_create(
                    name=f"{player.get_full_name()}",
                    folder_type=Folder.FolderType.PLAYER_PERSONAL,
                    parent=None,
                    owner=player
                )
                if created:
                    player_count += 1
        
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
