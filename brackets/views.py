from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework import status
from .models import Bracket, BracketRound, BracketMatch
from .serializers import BracketSerializer
from django.db import transaction
from rest_framework.exceptions import ValidationError
import random


class BracketViewSet(viewsets.ModelViewSet):
    queryset = Bracket.objects.all()
    serializer_class = BracketSerializer
    
    def perform_create(self, serializer):
        bracket = serializer.save()
        self._generate_bracket(bracket)

    def _generate_bracket(self, bracket):
        if bracket.elimination_type == 'single':
            self._generate_single_elimination(bracket)
        elif bracket.elimination_type == 'double':
            self._generate_double_elimination(bracket)
        elif bracket.elimination_type == 'round_robin':
            self._generate_round_robin(bracket)
        else:
            raise ValidationError("Invalid elimination type")
        
        # Update season end date after generating bracket
        self._update_season_end_date(bracket)
    
    def _update_season_end_date(self, bracket):
        """Update season end date to the latest game date if season end date is null"""
        season = bracket.season
        
        # Only update if season end_date is null
        if season.end_date is None:
            # Get all games for this season, including bracket games
            from games.models import Game
            latest_game = Game.objects.filter(
                season=season
            ).order_by('-date').first()
            
            if latest_game and latest_game.date:
                # Check if latest_game.date is already a date object or datetime
                if hasattr(latest_game.date, 'date'):
                    # It's a datetime object, extract the date part
                    season.end_date = latest_game.date.date()
                else:
                    # It's already a date object
                    season.end_date = latest_game.date
                season.save(update_fields=['end_date'])
                
    def _generate_single_elimination(self, bracket):
        teams = list(bracket.season.teams.all())
        if not teams:
            raise ValidationError("No teams found")

        random.shuffle(teams)

        total_teams = len(teams)
        total_rounds = (total_teams - 1).bit_length()
        
        # Create rounds
        rounds = []
        for n in range(total_rounds):
            round = BracketRound.objects.create(
                bracket=bracket,
                round_number=n+1
            )
            rounds.append(round)
        
        # Create matches with team assignments for first round
        for i in range(0, len(teams), 2):
            BracketMatch.objects.create(
                bracket=bracket,
                round=rounds[0],
                home_team=teams[i],
                away_team=teams[i+1] if i+1 < len(teams) else None
            )

        # Create empty matches for subsequent rounds
        for round_num in range(1, total_rounds):
            prev_matches_count = BracketMatch.objects.filter(round=rounds[round_num-1]).count()
            matches_needed = (prev_matches_count + 1) // 2
            
            for _ in range(matches_needed):
                BracketMatch.objects.create(
                    bracket=bracket,
                    round=rounds[round_num]
                )

        # Link matches between rounds safely
        for round_num in range(total_rounds-1):
            current_matches = list(BracketMatch.objects.filter(round=rounds[round_num]))
            next_matches = list(BracketMatch.objects.filter(round=rounds[round_num+1]))
            
            for idx, next_match in enumerate(next_matches):
                first_idx = idx * 2
                second_idx = idx * 2 + 1
                
                # Link first match
                if first_idx < len(current_matches):
                    current_matches[first_idx].next_match = next_match
                    current_matches[first_idx].save()
                
                # Link second match if exists
                if second_idx < len(current_matches):
                    current_matches[second_idx].next_match = next_match
                    current_matches[second_idx].save()
        
    def _is_power_of_2(self, n):
        """Check if n is a power of 2"""
        return n > 0 and (n & (n - 1)) == 0
    
    def _generate_double_elim_power_of_2(self, bracket, teams):
        """Generate double elimination for power of 2 teams (4, 8, 16, etc)"""
        total_teams = len(teams)
        upper_rounds_count = (total_teams - 1).bit_length()
        lower_rounds_count = 2 * (upper_rounds_count - 1)
        
        return {
            'upper_rounds_count': upper_rounds_count,
            'lower_rounds_count': lower_rounds_count,
            'teams_with_byes': [],
            'teams_in_first_round': teams,
            'byes_needed': 0,
            'next_power_of_2': total_teams
        }
    
    def _generate_double_elim_odd(self, bracket, teams):
        """Generate double elimination for odd number of teams (3, 5, 7, 9, etc)"""
        total_teams = len(teams)
        next_power_of_2 = 1 << (total_teams - 1).bit_length()
        byes_needed = next_power_of_2 - total_teams
        
        # For odd teams, we give byes to top seeds
        teams_with_byes = teams[:byes_needed]
        teams_in_first_round = teams[byes_needed:]
        
        # Upper rounds based on next power of 2
        upper_rounds_count = (next_power_of_2 - 1).bit_length()
        lower_rounds_count = 2 * (upper_rounds_count - 1)
        
        return {
            'upper_rounds_count': upper_rounds_count,
            'lower_rounds_count': lower_rounds_count,
            'teams_with_byes': teams_with_byes,
            'teams_in_first_round': teams_in_first_round,
            'byes_needed': byes_needed,
            'next_power_of_2': next_power_of_2
        }
    
    def _generate_double_elim_even_not_power_2(self, bracket, teams):
        """Generate double elimination for even but not power of 2 (6, 10, 12, 14, etc)"""
        total_teams = len(teams)
        next_power_of_2 = 1 << (total_teams - 1).bit_length()
        byes_needed = next_power_of_2 - total_teams
        
        # For even non-power-of-2, we give byes to top seeds
        teams_with_byes = teams[:byes_needed]
        teams_in_first_round = teams[byes_needed:]
        
        # Upper rounds based on next power of 2
        upper_rounds_count = (next_power_of_2 - 1).bit_length()
        lower_rounds_count = 2 * (upper_rounds_count - 1)
        
        return {
            'upper_rounds_count': upper_rounds_count,
            'lower_rounds_count': lower_rounds_count,
            'teams_with_byes': teams_with_byes,
            'teams_in_first_round': teams_in_first_round,
            'byes_needed': byes_needed,
            'next_power_of_2': next_power_of_2
        }
    
    def _generate_double_elimination(self, bracket):
        """
        Generate a double elimination bracket structure.
        - Creates upper bracket (winners bracket) and lower bracket (losers bracket)
        - Only first round matches get games created automatically
        - Subsequent matches get games created when their parent matches complete
        - Handles non-power-of-2 team counts with byes
        """
        teams = list(bracket.season.teams.all())
        if not teams:
            raise ValidationError("No teams found")

        random.shuffle(teams)
        total_teams = len(teams)
        
        # Determine which generation strategy to use
        if self._is_power_of_2(total_teams):
            print("Using power of 2 generation strategy")
            config = self._generate_double_elim_power_of_2(bracket, teams)
        elif total_teams % 2 == 1:  # Odd
            print("Using odd number of teams generation strategy")
            config = self._generate_double_elim_odd(bracket, teams)
        else:  # Even but not power of 2
            config = self._generate_double_elim_even_not_power_2(bracket, teams)
        
        # Extract configuration
        upper_rounds_count = config['upper_rounds_count']
        lower_rounds_count = config['lower_rounds_count']
        teams_with_byes = config['teams_with_byes']
        teams_in_first_round = config['teams_in_first_round']
        byes_needed = config['byes_needed']
        next_power_of_2 = config['next_power_of_2']
        
        # Create all rounds (upper + lower + grand final)
        upper_rounds = []
        lower_rounds = []
        
        # Create upper bracket rounds
        for i in range(upper_rounds_count):
            round_obj = BracketRound.objects.create(
                bracket=bracket,
                round_number=i + 1
            )
            upper_rounds.append(round_obj)
        
        # Create lower bracket rounds
        for i in range(lower_rounds_count):
            round_obj = BracketRound.objects.create(
                bracket=bracket,
                round_number=upper_rounds_count + i + 1
            )
            lower_rounds.append(round_obj)
        
        # Create grand final round
        grand_final_round = BracketRound.objects.create(
            bracket=bracket,
            round_number=upper_rounds_count + lower_rounds_count + 1
        )
        
        # === UPPER BRACKET FIRST ROUND ===
        # Create matches with teams for first round
        first_round_matches = []
        
        # Calculate how many R1 matches we need for a balanced bracket
        expected_r1_matches = next_power_of_2 // 2
        
        # Create matches for teams that play
        for i in range(0, len(teams_in_first_round), 2):
            home_team = teams_in_first_round[i]
            away_team = teams_in_first_round[i + 1] if i + 1 < len(teams_in_first_round) else None
            
            match = BracketMatch.objects.create(
                bracket=bracket,
                round=upper_rounds[0],
                home_team=home_team,
                away_team=away_team,
                is_filler=False
            )
            first_round_matches.append(match)
        
        # Create filler matches to balance the bracket visually
        while len(first_round_matches) < expected_r1_matches:
            match = BracketMatch.objects.create(
                bracket=bracket,
                round=upper_rounds[0],
                home_team=None,
                away_team=None,
                is_filler=True  # Mark as filler so it doesn't affect advancement
            )
            first_round_matches.append(match)
        
        # === CREATE EMPTY UPPER BRACKET MATCHES ===
        upper_bracket_structure = [first_round_matches]
        
        for round_idx in range(1, upper_rounds_count):
            # Calculate matches needed
            if round_idx == 1:
                # Round 2 = (R1 winners + bye teams) / 2
                total_teams_in_r2 = len(first_round_matches) + byes_needed
                matches_needed = (total_teams_in_r2 + 1) // 2
            else:
                # Subsequent rounds use power-of-2 structure
                matches_needed = next_power_of_2 // (2 ** (round_idx + 1))
            
            current_round_matches = []
            
            for _ in range(matches_needed):
                match = BracketMatch.objects.create(
                    bracket=bracket,
                    round=upper_rounds[round_idx]
                )
                current_round_matches.append(match)
            
            upper_bracket_structure.append(current_round_matches)
        
        # === LINK UPPER BRACKET MATCHES ===
        for round_idx in range(upper_rounds_count - 1):
            current_matches = upper_bracket_structure[round_idx]
            next_matches = upper_bracket_structure[round_idx + 1]
            
            # Assign teams with byes to the END of round 2 matches
            if round_idx == 0 and byes_needed > 0:
                matches_without_byes = len(next_matches) - byes_needed
                for bye_idx, bye_team in enumerate(teams_with_byes):
                    target_match_idx = matches_without_byes + bye_idx
                    if target_match_idx < len(next_matches):
                        next_matches[target_match_idx].home_team = bye_team
                        next_matches[target_match_idx].save(update_fields=['home_team'])
            
            # Standard 2:1 linking for all rounds (skip filler matches)
            for match_idx, next_match in enumerate(next_matches):
                first_idx = match_idx * 2
                second_idx = match_idx * 2 + 1
                
                if first_idx < len(current_matches) and not current_matches[first_idx].is_filler:
                    current_matches[first_idx].next_match = next_match
                    current_matches[first_idx].save(update_fields=['next_match'])
                
                if second_idx < len(current_matches) and not current_matches[second_idx].is_filler:
                    current_matches[second_idx].next_match = next_match
                    current_matches[second_idx].save(update_fields=['next_match'])
        
        # === CREATE EMPTY LOWER BRACKET MATCHES ===
        lower_bracket_structure = []
        
        # Lower bracket round 1: receives losers from upper bracket round 1
        # Count only non-filler R1 matches for actual losers
        actual_r1_matches = [m for m in first_round_matches if not m.is_filler]
        num_r1_losers = len(actual_r1_matches)
        
        # For LB R1, we need floor(losers / 2) matches
        # If odd number of losers, one will get a bye to LB R2 (merge round)
        lb_r1_count = num_r1_losers // 2
        lb_r1_matches = []
        
        if lb_r1_count > 0:
            for _ in range(lb_r1_count):
                match = BracketMatch.objects.create(
                    bracket=bracket,
                    round=lower_rounds[0],
                    is_filler=False
                )
                lb_r1_matches.append(match)
        
        lower_bracket_structure.append(lb_r1_matches)
        
        # Subsequent lower bracket rounds alternate between:
        # - Rounds that only receive winners from previous lower round
        # - Rounds that receive winners from lower + losers from upper
        for lb_round_idx in range(1, lower_rounds_count):
            is_merge_round = (lb_round_idx % 2 == 1)  # Odd rounds merge upper losers
            
            if is_merge_round:
                # This round gets winners from prev lower + losers from upper
                # Calculate which upper bracket round feeds into this lower round
                ub_source_round_idx = (lb_round_idx + 1) // 2
                
                prev_lower_matches = lower_bracket_structure[lb_round_idx - 1]
                
                # Calculate losers from upper bracket
                if ub_source_round_idx < len(upper_bracket_structure):
                    ub_matches = upper_bracket_structure[ub_source_round_idx]
                    ub_losers_count = len([m for m in ub_matches if not m.is_filler])
                else:
                    ub_losers_count = 0
                
                # Winners from previous LB round
                lb_winners_count = len(prev_lower_matches)  # Each match produces 1 winner
                
                # Special handling for LB R2 (first merge round after LB R1)
                if lb_round_idx == 1:
                    # Check if there's an odd R1 loser getting a bye
                    actual_r1_matches = [m for m in first_round_matches if not m.is_filler]
                    has_r1_bye = len(actual_r1_matches) % 2 == 1
                    
                    if has_r1_bye:
                        # One R1 loser bypassed LB R1 and goes directly here
                        # This team will be matched with a UB R2 loser
                        # So we need: lb_winners + ub_losers + 1 (bye)
                        total_teams = lb_winners_count + ub_losers_count + 1
                    else:
                        total_teams = lb_winners_count + ub_losers_count
                else:
                    # Normal merge round
                    total_teams = lb_winners_count + ub_losers_count
                
                # Calculate matches needed
                matches_needed = (total_teams + 1) // 2
            else:
                # This round only gets winners from previous lower round
                prev_lower_matches = lower_bracket_structure[lb_round_idx - 1]
                matches_needed = (len(prev_lower_matches) + 1) // 2
            
            current_lb_matches = []
            
            # Create matches
            for _ in range(matches_needed):
                match = BracketMatch.objects.create(
                    bracket=bracket,
                    round=lower_rounds[lb_round_idx],
                    is_filler=False
                )
                current_lb_matches.append(match)
            
            lower_bracket_structure.append(current_lb_matches)
        
        # === LINK FIRST ROUND UPPER TO LOWER BRACKET ===
        # Losers from upper bracket first round go to lower bracket first round
        # Skip filler matches - they don't advance anyone
        # If there's an odd number of R1 losers, the last one gets a bye to LB R2
        
        actual_r1_matches = [m for m in first_round_matches if not m.is_filler]
        
        for idx, ub_match in enumerate(actual_r1_matches):
            lb_match_idx = idx // 2
            
            if lb_match_idx < len(lb_r1_matches):
                # This loser goes to LB R1
                ub_match.next_loser_match = lb_r1_matches[lb_match_idx]
                ub_match.save(update_fields=['next_loser_match'])
            else:
                # Odd loser out gets bye to LB R2 (first merge round)
                # LB R2 is at index 1 in lower_bracket_structure
                if len(lower_bracket_structure) > 1:
                    lb_r2_matches = lower_bracket_structure[1]
                    if len(lb_r2_matches) > 0:
                        # Find the first LB R2 match that doesn't already have a bye team assigned
                        # This loser will be paired with the UB R2 loser in that match
                        ub_match.next_loser_match = lb_r2_matches[-1]  # Use last match for bye
                        ub_match.save(update_fields=['next_loser_match'])
        
        # === LINK UPPER BRACKET LOSERS TO LOWER BRACKET ===
        # Upper bracket losers feed into specific lower bracket rounds
        # UB Round 1 losers already linked to LB Round 0 above
        # UB Round 2 losers go to LB Round 1 (first merge round after LB R1)
        # UB Round 3 losers go to LB Round 3 (second merge round)
        # Pattern: UB Round N (N>1) losers go to LB Round (N-1)*2 - 1
        for ub_round_idx in range(1, upper_rounds_count):
            # Calculate which lower bracket round receives these losers
            # For UB round 2 (idx 1): (1)*2 - 1 = 1 (LB round 2, which is merge)
            # For UB round 3 (idx 2): (2)*2 - 1 = 3 (LB round 4, which is merge)
            lb_target_round_idx = (ub_round_idx * 2) - 1
            
            if lb_target_round_idx < len(lower_bracket_structure):
                upper_matches = upper_bracket_structure[ub_round_idx]
                lower_matches = lower_bracket_structure[lb_target_round_idx]
                
                # Each upper bracket match's loser goes to a specific lower bracket match
                for idx, ub_match in enumerate(upper_matches):
                    if idx < len(lower_matches):
                        ub_match.next_loser_match = lower_matches[idx]
                        ub_match.save(update_fields=['next_loser_match'])
        
        # === LINK LOWER BRACKET INTERNALLY ===
        for lb_round_idx in range(lower_rounds_count - 1):
            current_lb_matches = lower_bracket_structure[lb_round_idx]
            next_lb_matches = lower_bracket_structure[lb_round_idx + 1]
            
            is_next_merge = ((lb_round_idx + 1) % 2 == 1)
            
            if is_next_merge:
                # Each match advances winner to corresponding next match
                for idx, match in enumerate(current_lb_matches):
                    if idx < len(next_lb_matches):
                        match.next_match = next_lb_matches[idx]
                        match.save(update_fields=['next_match'])
            else:
                # Two matches feed into one
                for next_idx, next_match in enumerate(next_lb_matches):
                    first_idx = next_idx * 2
                    second_idx = next_idx * 2 + 1
                    
                    if first_idx < len(current_lb_matches):
                        current_lb_matches[first_idx].next_match = next_match
                        current_lb_matches[first_idx].save(update_fields=['next_match'])
                    
                    if second_idx < len(current_lb_matches):
                        current_lb_matches[second_idx].next_match = next_match
                        current_lb_matches[second_idx].save(update_fields=['next_match'])
        
        # === CREATE GRAND FINAL MATCH ===
        grand_final_match = BracketMatch.objects.create(
            bracket=bracket,
            round=grand_final_round
        )
        
        # Upper bracket winner goes to grand final
        if upper_bracket_structure[-1]:
            upper_bracket_structure[-1][0].next_match = grand_final_match
            upper_bracket_structure[-1][0].save(update_fields=['next_match'])
        
        # Lower bracket winner goes to grand final
        if lower_bracket_structure:
            lower_bracket_structure[-1][0].next_match = grand_final_match
            lower_bracket_structure[-1][0].save(update_fields=['next_match'])
    
    def _generate_round_robin(self, bracket):
        teams = list(bracket.season.teams.all())
        if not teams:
            raise ValidationError("No teams found")

        random.shuffle(teams)  # Shuffle to randomize the bracket

        num_teams = len(teams)
        is_odd = num_teams % 2 != 0

        # If odd number of teams, add a "bye" placeholder (None)
        if is_odd:
            teams.append(None)
            num_teams += 1

        total_rounds = num_teams - 1
        for round_number in range(1, total_rounds + 1):
            round_obj = BracketRound.objects.create(
                bracket=bracket,
                round_number=round_number
            )

            matchups = []
            for i in range(num_teams // 2):
                home = teams[i]
                away = teams[num_teams - 1 - i]
                if home is not None and away is not None:
                    matchups.append((home, away))

            # Create matches
            for home, away in matchups:
                BracketMatch.objects.create(
                    bracket=bracket,
                    round=round_obj,
                    home_team=home,
                    away_team=away
                )

            # Correct circle method rotation
            teams = [teams[0]] + teams[-1:] + teams[1:-1]

        
    def _create_next_round(self, bracket):
        # Only create next round for single elimination
        # Double elimination and round robin have all rounds pre-created
        if bracket.elimination_type != 'single':
            return
            
        current_round = bracket.rounds.get(round_number=bracket.current_round)
        next_round_number = bracket.current_round + 1
        
        matches = list(current_round.matches.all().order_by('id'))

        if len(matches) < 2:
            # Tournament is complete (final match played)
            final_match = matches[0]
            bracket.is_complete = Bracket.is_complete = True
            bracket.winner = final_match.winner
            bracket.save(update_fields=["is_complete"])
            return

        # Check if next round already exists to avoid duplicates
        if bracket.rounds.filter(round_number=next_round_number).exists():
            return

        next_round = bracket.rounds.create(round_number=next_round_number)

        for i in range(0, len(matches), 2):
            match1 = matches[i]
            match2 = matches[i + 1] if i + 1 < len(matches) else None

            # Skip if next_match is already assigned
            if match1.next_match or (match2 and match2.next_match):
                continue

            next_match = BracketMatch.objects.create(
                bracket=bracket,
                round=next_round
            )

            match1.next_match = next_match
            match1.save(update_fields=['next_match'])

            if match2:
                match2.next_match = next_match
                match2.save(update_fields=['next_match'])

        bracket.current_round = next_round_number
        bracket.save(update_fields=['current_round'])
        
    @action(detail=False, methods=['get'], url_path=r'for_season/(?P<season_id>\d+)')
    def for_season(self, request, season_id=None):
        try:
            bracket = Bracket.objects.select_related('season').prefetch_related(
                'rounds__matches'
            ).get(season_id=season_id)
        except Bracket.DoesNotExist:
            return Response(
                {"detail": "Bracket for this season does not exist."},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = self.get_serializer(bracket)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def fix_invalid_winners(self, request):
        """
        Fix all bracket matches where the winner does not match one of the participating teams.
        """
        fixed_matches = []
        error_matches = []
        
        # Find matches with incorrect winners
        for match in BracketMatch.objects.select_related('home_team', 'away_team', 'winner', 'game').all():
            if match.winner and match.home_team and match.away_team:
                if match.winner.id not in [match.home_team.id, match.away_team.id]:
                    match_info = {
                        'id': match.id,
                        'home_team': {
                            'id': match.home_team.id,
                            'name': match.home_team.name
                        },
                        'away_team': {
                            'id': match.away_team.id,
                            'name': match.away_team.name
                        },
                        'invalid_winner': {
                            'id': match.winner.id,
                            'name': match.winner.name
                        }
                    }
                    
                    # Try to fix based on the game scores if available
                    if match.game:
                        game = match.game
                        if game.home_team_score > game.away_team_score:
                            old_winner_id = match.winner.id
                            match.winner = match.home_team
                            match.save(update_fields=["winner"])
                            
                            match_info['action'] = 'fixed'
                            match_info['new_winner'] = {
                                'id': match.home_team.id,
                                'name': match.home_team.name,
                                'reason': 'home team score higher'
                            }
                            fixed_matches.append(match_info)
                        elif game.away_team_score > game.home_team_score:
                            old_winner_id = match.winner.id
                            match.winner = match.away_team
                            match.save(update_fields=["winner"])
                            
                            match_info['action'] = 'fixed'
                            match_info['new_winner'] = {
                                'id': match.away_team.id,
                                'name': match.away_team.name,
                                'reason': 'away team score higher'
                            }
                            fixed_matches.append(match_info)
                        else:
                            match_info['action'] = 'error'
                            match_info['reason'] = 'game scores tied'
                            error_matches.append(match_info)
                    else:
                        match_info['action'] = 'error'
                        match_info['reason'] = 'no associated game'
                        error_matches.append(match_info)
        
        return Response({
            'fixed_count': len(fixed_matches),
            'error_count': len(error_matches),
            'fixed_matches': fixed_matches,
            'error_matches': error_matches
        })
