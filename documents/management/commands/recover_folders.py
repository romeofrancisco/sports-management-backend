"""
Management command to recover deleted personal folders for coaches and players.
Usage: python manage.py recover_folders
"""
from django.core.management.base import BaseCommand
from documents.folder_utils import recover_all_user_folders


class Command(BaseCommand):
    help = 'Recover deleted personal folders for all coaches and players'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output',
        )

    def handle(self, *args, **options):
        verbose = options['verbose']
        
        self.stdout.write(self.style.WARNING('Starting folder recovery...'))
        self.stdout.write('')
        
        # Recover all folders
        stats = recover_all_user_folders()
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Recovery completed!'))
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Summary:'))
        self.stdout.write(f"  Root folders created: {stats['root_folders_created']}")
        self.stdout.write(f"  Coach folders created: {stats['coach_folders_created']}")
        self.stdout.write(f"  Player folders created: {stats['player_folders_created']}")
        self.stdout.write(f"  Total folders created: {stats['total_created']}")
        self.stdout.write('')
        
        if stats['total_created'] == 0:
            self.stdout.write(self.style.SUCCESS('✓ All folders are intact. No recovery needed.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'✓ Successfully recovered {stats["total_created"]} missing folders.'))
