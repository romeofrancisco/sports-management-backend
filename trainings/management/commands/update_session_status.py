from django.core.management.base import BaseCommand
from django.utils import timezone
from trainings.models import TrainingSession


class Command(BaseCommand):
    help = 'Update training session statuses based on current time'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Show what would be updated without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        sessions = TrainingSession.objects.all()
        updated_count = 0
        
        self.stdout.write(
            self.style.SUCCESS(f'Processing {sessions.count()} training sessions...')
        )
        
        for session in sessions:
            old_status = session.status
            new_status = session.get_auto_status()
            
            if old_status != new_status:
                if not dry_run:
                    session.status = new_status
                    session.save(update_fields=['status'])
                
                updated_count += 1
                self.stdout.write(
                    f'Session "{session.title}" ({session.date}): {old_status} -> {new_status}'
                    + (' (DRY RUN)' if dry_run else '')
                )
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'DRY RUN: Would update {updated_count} sessions')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'Successfully updated {updated_count} training sessions')
            )
