from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework import status
from .models import Bracket, BracketRound, BracketMatch
from .serializers import BracketSerializer
from teams.models import Team

class BracketViewSet(viewsets.ModelViewSet):
    queryset = Bracket.objects.all()
    serializer_class = BracketSerializer

    @action(detail=True, methods=['post'])
    def generate(self, request, pk=None):
        """Generate a bracket for a league."""
        bracket = self.get_object()  # Retrieve the existing bracket object
        
        # If no bracket exists for the given pk, return a 404 error
        if not bracket:
            return Response({"error": "Bracket not found."}, status=status.HTTP_404_NOT_FOUND)
        
        # If the bracket already exists and has an associated season, don't require a season_id
        if bracket.season is None:
            season_id = request.data.get('season_id')
            if not season_id:
                return Response({"error": "Season ID is required to create a new bracket."}, status=status.HTTP_400_BAD_REQUEST)
            
            # If no season is assigned, assign it here
            bracket.season_id = season_id
            bracket.save()

        self._generate_bracket(bracket)
        return Response({"message": "Bracket generated successfully."}, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'], url_path=r'for_season/(?P<season_id>\d+)')
    def for_season(self, request, season_id=None):
        """Get brackets for a specific season with rounds and matches"""
        brackets = Bracket.objects.filter(season_id=season_id).prefetch_related(
            'rounds__matches'  # Prefetch rounds and their matches
        )
        serializer = self.get_serializer(brackets, many=True)
        return Response(serializer.data)

    def _generate_bracket(self, bracket):
        """Logic to generate the bracket based on the elimination type."""
        if bracket.elimination_type == 'single':
            self._generate_single_elimination(bracket)
        elif bracket.elimination_type == 'double':
            self._generate_double_elimination(bracket)
        else:
            return Response({"error": "Unsupported elimination type."}, status=status.HTTP_400_BAD_REQUEST)

    def _generate_single_elimination(self, bracket):
        teams = list(bracket.season.league.teams.all())
        if not teams:
            return Response({"error": "No teams found for the league."}, status=status.HTTP_400_BAD_REQUEST)

        round_number = 1
        while len(teams) > 1:
            round_ = BracketRound.objects.create(bracket=bracket, round_number=round_number)
            match_number = 1
            for i in range(0, len(teams), 2):
                home = teams[i]
                away = teams[i + 1] if i + 1 < len(teams) else None
                BracketMatch.objects.create(
                    bracket=bracket,
                    round=round_,
                    home_team=home,
                    away_team=away,
                )
                match_number += 1
            teams = [match.home_team for match in round_.bracketmatch_set.all() if match.home_team]  # advancing teams
            round_number += 1

    def _generate_double_elimination(self, bracket):
        teams = list(bracket.season.league.teams.all())
        if not teams:
            return Response({"error": "No teams found for the league."}, status=status.HTTP_400_BAD_REQUEST)

        round_number = 1
        while len(teams) > 1:
            round_ = BracketRound.objects.create(bracket=bracket, round_number=round_number)
            match_number = 1
            for i in range(0, len(teams), 2):
                home = teams[i]
                away = teams[i + 1] if i + 1 < len(teams) else None
                BracketMatch.objects.create(
                    bracket=bracket,
                    round=round_,
                    home_team=home,
                    away_team=away,
                )
                match_number += 1
            teams = [match.home_team for match in round_.bracketmatch_set.all() if match.home_team]  # advancing teams
            round_number += 1
