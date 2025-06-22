from django.core.management.base import BaseCommand
from teams.models import Team, Coach


class Command(BaseCommand):
    help = 'Assign some coaches as assistant coaches to teams that already have head coaches'

    def handle(self, *args, **options):
        # Get teams that have head coaches but no assistant coaches
        teams_needing_assistants = Team.objects.filter(
            head_coach__isnull=False, 
            assistant_coach__isnull=True
        )
        available_coaches = Coach.objects.all()
        
        self.stdout.write(f"Found {teams_needing_assistants.count()} teams needing assistant coaches")
        self.stdout.write(f"Found {available_coaches.count()} available coaches")
        
        if not available_coaches.exists():
            self.stdout.write(self.style.WARNING('No coaches found.'))
            return
        
        updated_count = 0
        for team in teams_needing_assistants[:5]:  # Limit to first 5 teams
            # Find a different coach that can handle this team's sport
            suitable_coach = None
            for coach in available_coaches:
                # Don't assign the same coach as both head and assistant
                if coach == team.head_coach:
                    continue
                    
                coach_sports = coach.sports.all()
                if team.sport in coach_sports:
                    suitable_coach = coach
                    break
            
            if suitable_coach:
                team.assistant_coach = suitable_coach
                team.save()
                updated_count += 1
                self.stdout.write(f"Assigned {suitable_coach.user.get_full_name()} as assistant coach to {team.name}")
            else:
                self.stdout.write(self.style.WARNING(f"No suitable assistant coach found for {team.name}"))
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully assigned assistant coaches to {updated_count} teams.')
        )
