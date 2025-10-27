from django.core.management.base import BaseCommand
from documents.models import Folder


class Command(BaseCommand):
    help = 'Ensure root folders (Public, Coaches) exist'

    def handle(self, *args, **options):
        self.stdout.write('Checking root folders...\n')
        
        # Create/Check Public folder
        public_folder, created = Folder.objects.get_or_create(
            name='Public',
            folder_type=Folder.FolderType.PUBLIC,
            parent=None,
            defaults={'owner': None}
        )
        if created:
            self.stdout.write(self.style.SUCCESS('✓ Created Public root folder'))
        else:
            self.stdout.write(self.style.WARNING('✓ Public folder already exists'))
        
        # Create/Check Coaches folder
        coaches_folder, created = Folder.objects.get_or_create(
            name='Coaches',
            folder_type=Folder.FolderType.COACHES,
            parent=None,
            defaults={'owner': None}
        )
        if created:
            self.stdout.write(self.style.SUCCESS('✓ Created Coaches root folder'))
        else:
            self.stdout.write(self.style.WARNING('✓ Coaches folder already exists'))
        
        # Display all root folders
        self.stdout.write('\n' + self.style.SUCCESS('Root folders in system:'))
        root_folders = Folder.objects.filter(parent__isnull=True)
        for folder in root_folders:
            self.stdout.write(f'  - {folder.name} ({folder.folder_type})')
        
        self.stdout.write('\n' + self.style.SUCCESS('✓ Root folders verified!'))
