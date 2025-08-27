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
        
    def _generate_double_elimination(self, bracket):
        # Implement your double elimination logic here or leave as a placeholder
        raise NotImplementedError("Double elimination generation is not implemented yet.")
    
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
