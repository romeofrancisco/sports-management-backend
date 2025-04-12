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
                
    def _generate_single_elimination(self, bracket):
        teams = list(bracket.season.league.teams.all())
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
        
    def _generate_double_elimination(self, bracket):
        # Implement your double elimination logic here or leave as a placeholder
        raise NotImplementedError("Double elimination generation is not implemented yet.")
    
    def _generate_round_robin(self, bracket):
        teams = list(bracket.season.league.teams.all())
        if not teams:
            raise ValidationError("No teams found")

        num_teams = len(teams)
        is_odd = num_teams % 2 != 0

        # If odd number of teams, add a "bye" placeholder (None)
        if is_odd:
            teams.append(None)
            num_teams += 1

        total_rounds = num_teams - 1
        half_size = num_teams // 2

        # Generate initial team order (fixed first, rotating rest)
        teams_fixed = teams[0]
        rotating = teams[1:]

        for round_number in range(1, total_rounds + 1):
            round_obj = BracketRound.objects.create(
                bracket=bracket,
                round_number=round_number
            )

            matchups = []

            # Pair the fixed team
            first = teams_fixed
            second = rotating[-1]
            matchups.append((first, second))

            # Pair remaining teams
            for i in range(half_size - 1):
                home = rotating[i]
                away = rotating[-i - 2]
                matchups.append((home, away))

            # Create matches
            for home, away in matchups:
                if home is None or away is None:
                    continue  # Skip matches involving "bye"
                BracketMatch.objects.create(
                    bracket=bracket,
                    round=round_obj,
                    home_team=home,
                    away_team=away
                )

            # Rotate teams
            rotating = [rotating[-1]] + rotating[:-1]

        
    def _create_next_round(self, bracket):
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
