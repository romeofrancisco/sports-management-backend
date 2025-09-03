from django.core.management.base import BaseCommand
from django.db import transaction
from brackets.models import Bracket, BracketMatch
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fix bracket matches where both teams show as lost'

    def add_arguments(self, parser):
        parser.add_argument('--bracket', type=int, help='Specific bracket ID to fix')
        parser.add_argument('--dry-run', action='store_true', help='Show what would be fixed without making changes')

    def handle(self, *args, **options):
        bracket_id = options.get('bracket')
        dry_run = options.get('dry_run')

        if bracket_id:
            try:
                bracket = Bracket.objects.get(id=bracket_id)
                brackets = [bracket]
            except Bracket.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Bracket with ID {bracket_id} not found'))
                return
        else:
            brackets = Bracket.objects.all()

        for bracket in brackets:
            self.stdout.write(f'Checking bracket: {bracket} (ID: {bracket.id})')
            self._fix_bracket_progression(bracket, dry_run)

    def _fix_bracket_progression(self, bracket, dry_run):
        """Fix the bracket progression by correctly assigning winners to next round matches"""
        rounds = bracket.rounds.order_by('round_number')
        
        for round_obj in rounds:
            round_number = round_obj.round_number
            self.stdout.write(f'  Checking Round {round_number}')
            
            # Get matches in this round
            current_matches = list(round_obj.matches.order_by('id'))
            
            # Check if this round is complete (all matches have winners)
            incomplete_matches = [m for m in current_matches if not m.winner]
            if incomplete_matches:
                self.stdout.write(f'    Round {round_number} is incomplete - {len(incomplete_matches)} matches without winners')
                continue
                
            # Get next round
            next_round = bracket.rounds.filter(round_number=round_number + 1).first()
            if not next_round:
                self.stdout.write(f'    Round {round_number} is the final round')
                continue
                
            next_matches = list(next_round.matches.order_by('id'))
            self.stdout.write(f'    Found {len(current_matches)} current matches and {len(next_matches)} next matches')
            
            # Fix team assignments in next round
            fixes_made = 0
            for i, next_match in enumerate(next_matches):
                # Each next round match should get winners from two current round matches
                first_match_idx = i * 2
                second_match_idx = i * 2 + 1
                
                expected_home = None
                expected_away = None
                
                if first_match_idx < len(current_matches):
                    expected_home = current_matches[first_match_idx].winner
                    
                if second_match_idx < len(current_matches):
                    expected_away = current_matches[second_match_idx].winner
                
                # Check and fix home team
                if expected_home and next_match.home_team != expected_home:
                    self.stdout.write(f'    Match {next_match.id}: Home team should be {expected_home} but is {next_match.home_team}')
                    if not dry_run:
                        next_match.home_team = expected_home
                        fixes_made += 1
                
                # Check and fix away team
                if expected_away and next_match.away_team != expected_away:
                    self.stdout.write(f'    Match {next_match.id}: Away team should be {expected_away} but is {next_match.away_team}')
                    if not dry_run:
                        next_match.away_team = expected_away
                        fixes_made += 1
                
                # Save changes
                if fixes_made > 0 and not dry_run:
                    next_match.save(update_fields=['home_team', 'away_team'])
            
            if fixes_made > 0:
                self.stdout.write(self.style.SUCCESS(f'    Fixed {fixes_made} team assignments in round {next_round.round_number}'))
            elif not dry_run:
                self.stdout.write(f'    No fixes needed for round {next_round.round_number}')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No changes were made'))
