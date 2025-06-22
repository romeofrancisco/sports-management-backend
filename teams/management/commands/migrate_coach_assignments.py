from django.core.management.base import BaseCommand
from teams.models import Team, Coach


class Command(BaseCommand):
    help = 'Migrate existing coach assignments to new head_coach/assistant_coach structure'

    def handle(self, *args, **options):
        # Get all teams without head coaches
        teams_without_coaches = Team.objects.filter(head_coach__isnull=True, assistant_coach__isnull=True)
        coaches = Coach.objects.all()
        
        self.stdout.write(f"Found {teams_without_coaches.count()} teams without coaches")
        self.stdout.write(f"Found {coaches.count()} available coaches")
        
        if not coaches.exists():
            self.stdout.write(self.style.WARNING('No coaches found. Please create coaches first.'))
            return
        
        updated_count = 0
        for team in teams_without_coaches:
            # Find a coach that can handle this team's sport
            suitable_coach = None
            for coach in coaches:
                coach_sports = coach.sports.all()
                if team.sport in coach_sports:
                    suitable_coach = coach
                    break
            
            if suitable_coach:
                team.head_coach = suitable_coach
                team.save()
                updated_count += 1
                self.stdout.write(f"Assigned {suitable_coach.user.get_full_name()} as head coach to {team.name} ({team.sport.name})")
            else:
                self.stdout.write(self.style.WARNING(f"No suitable coach found for {team.name} ({team.sport.name})"))
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully assigned coaches to {updated_count} teams.')
        )
