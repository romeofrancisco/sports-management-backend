from django.core.management.base import BaseCommand
from teams.models import Team
from chat.models import TeamChat

class Command(BaseCommand):
    help = 'Create TeamChat instances for existing teams'

    def handle(self, *args, **options):
        teams_without_chat = Team.objects.filter(chat_room__isnull=True)
        created_count = 0
        
        for team in teams_without_chat:
            TeamChat.objects.create(team=team)
            created_count += 1
            self.stdout.write(
                self.style.SUCCESS(f'Created chat room for team: {team.name}')
            )
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully created {created_count} team chat rooms')
        )
