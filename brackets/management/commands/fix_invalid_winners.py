from django.core.management.base import BaseCommand
from brackets.models import BracketMatch
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Fix invalid winners in bracket matches'

    def handle(self, *args, **options):
        fixed_count = 0
        
        # Find matches with incorrect winners
        for match in BracketMatch.objects.select_related('home_team', 'away_team', 'winner', 'game').all():
            if match.winner and match.home_team and match.away_team:
                if match.winner.id not in [match.home_team.id, match.away_team.id]:
                    self.stdout.write(f"Match {match.id}: Home={match.home_team.id} ({match.home_team.name}), " +
                                      f"Away={match.away_team.id} ({match.away_team.name}), " +
                                      f"Invalid Winner={match.winner.id} ({match.winner.name})")
                    
                    # Try to fix based on the game scores if available
                    if match.game:
                        game = match.game
                        if game.home_team_score > game.away_team_score:
                            match.winner = match.home_team
                            match.save(update_fields=["winner"])
                            fixed_count += 1
                            self.stdout.write(self.style.SUCCESS(
                                f"  Fixed: Set winner to home team {match.home_team.id} ({match.home_team.name})"))
                        elif game.away_team_score > game.home_team_score:
                            match.winner = match.away_team
                            match.save(update_fields=["winner"])
                            fixed_count += 1
                            self.stdout.write(self.style.SUCCESS(
                                f"  Fixed: Set winner to away team {match.away_team.id} ({match.away_team.name})"))
                        else:
                            self.stdout.write(self.style.WARNING(f"  Cannot fix: Game scores are tied"))
                    else:
                        self.stdout.write(self.style.WARNING(f"  Cannot fix: No game associated with this match"))
        
        self.stdout.write(self.style.SUCCESS(f'Fixed {fixed_count} matches with invalid winners'))