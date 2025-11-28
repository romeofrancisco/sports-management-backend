"""
Management command to clean up Google Drive files
"""

from django.core.management.base import BaseCommand
from documents.google_drive_service import get_drive_service
from documents.models import Document


class Command(BaseCommand):
    help = 'Clean up Google Drive files and reset document links'

    def add_arguments(self, parser):
        parser.add_argument(
            '--list',
            action='store_true',
            help='List all files in Google Drive without deleting',
        )
        parser.add_argument(
            '--quota',
            action='store_true',
            help='Show storage quota information',
        )
        parser.add_argument(
            '--delete-all',
            action='store_true',
            help='Delete ALL files from Google Drive (use with caution!)',
        )
        parser.add_argument(
            '--reset-links',
            action='store_true',
            help='Clear all google_drive_id values from documents',
        )

    def handle(self, *args, **options):
        try:
            drive_service = get_drive_service()
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Failed to initialize Google Drive service: {e}'))
            return

        if options['quota']:
            self.show_quota(drive_service)
            return

        if options['list']:
            self.list_files(drive_service)
            return

        if options['delete_all']:
            self.delete_all_files(drive_service)
            return

        if options['reset_links']:
            self.reset_document_links()
            return

        # Default: show help
        self.stdout.write(self.style.WARNING('No action specified. Use --help for options.'))

    def show_quota(self, drive_service):
        """Show storage quota information"""
        self.stdout.write('Fetching storage quota...')
        
        try:
            quota = drive_service.get_storage_quota()
            
            limit = int(quota.get('limit', 0))
            usage = int(quota.get('usage', 0))
            usage_drive = int(quota.get('usageInDrive', 0))
            usage_trash = int(quota.get('usageInDriveTrash', 0))
            
            def format_bytes(b):
                for unit in ['B', 'KB', 'MB', 'GB']:
                    if b < 1024:
                        return f"{b:.2f} {unit}"
                    b /= 1024
                return f"{b:.2f} TB"
            
            self.stdout.write(self.style.SUCCESS(f'\nStorage Quota:'))
            self.stdout.write(f'  Limit: {format_bytes(limit)}')
            self.stdout.write(f'  Used: {format_bytes(usage)} ({usage/limit*100:.1f}%)')
            self.stdout.write(f'  In Drive: {format_bytes(usage_drive)}')
            self.stdout.write(f'  In Trash: {format_bytes(usage_trash)}')
            
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Failed to get quota: {e}'))

    def list_files(self, drive_service):
        """List all files in Google Drive"""
        self.stdout.write('Listing files in Google Drive...')
        
        files = drive_service.list_all_files()
        
        if not files:
            self.stdout.write(self.style.SUCCESS('No files found.'))
            return
        
        self.stdout.write(self.style.SUCCESS(f'\nFound {len(files)} files:\n'))
        
        total_size = 0
        for file in files:
            size = int(file.get('size', 0))
            total_size += size
            size_str = f"{size/1024/1024:.2f} MB" if size > 0 else "N/A"
            self.stdout.write(f"  {file['name']} ({file['id']}) - {size_str}")
        
        self.stdout.write(f'\nTotal size: {total_size/1024/1024:.2f} MB')

    def delete_all_files(self, drive_service):
        """Delete all files from Google Drive"""
        files = drive_service.list_all_files()
        
        if not files:
            self.stdout.write(self.style.SUCCESS('No files to delete.'))
            return
        
        self.stdout.write(self.style.WARNING(f'\nAbout to delete {len(files)} files from Google Drive!'))
        confirm = input('Are you sure? Type "yes" to confirm: ')
        
        if confirm.lower() != 'yes':
            self.stdout.write('Cancelled.')
            return
        
        deleted = drive_service.delete_all_files()
        self.stdout.write(self.style.SUCCESS(f'\nDeleted {deleted} files.'))
        
        # Also clear document links
        self.reset_document_links()

    def reset_document_links(self):
        """Clear all google_drive_id values from documents"""
        count = Document.objects.exclude(google_drive_id__isnull=True).exclude(google_drive_id='').count()
        
        if count == 0:
            self.stdout.write(self.style.SUCCESS('No documents with Google Drive links found.'))
            return
        
        self.stdout.write(f'Clearing Google Drive links from {count} documents...')
        Document.objects.exclude(google_drive_id__isnull=True).update(google_drive_id=None)
        self.stdout.write(self.style.SUCCESS(f'Cleared {count} document links.'))
