from rest_framework import serializers
from .models import Bracket, BracketRound, BracketMatch
from teams.models import Team
from games.models import Game

class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ['id', 'name', 'logo']

class BracketMatchSerializer(serializers.ModelSerializer):
    home_team = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all(), required=False, write_only=True)
    away_team = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all(), required=False, write_only=True)
    
        # For read operations
    home_team_details = TeamSerializer(source='home_team', read_only=True)
    away_team_details = TeamSerializer(source='away_team', read_only=True)

    game = serializers.PrimaryKeyRelatedField(queryset=Game.objects.all(), required=False,)
    
    next_match_id = serializers.IntegerField(
        source='next_match.id', 
        read_only=True,
        allow_null=True
    )
    
    next_loser_match_id = serializers.IntegerField(
        source='next_loser_match.id',
        read_only=True,
        allow_null=True
    )
    
    date = serializers.SerializerMethodField()

    class Meta:
        model = BracketMatch
        fields = [
            'id', 'bracket', 'round', 
            'home_team', 'away_team',  # For input
            'home_team_details', 'away_team_details',  # For output
            'game','winner', 'next_match_id', 'next_loser_match_id', "date",
        ]
        
    def get_date(self, obj):
        if obj.game and obj.game.date:
            return obj.game.date
        return None

class BracketRoundSerializer(serializers.ModelSerializer):
    matches = BracketMatchSerializer(many=True, read_only=True)

    class Meta:
        model = BracketRound
        fields = ['id', 'bracket', 'round_number', 'created_at', 'matches']

class BracketSerializer(serializers.ModelSerializer):
    rounds = BracketRoundSerializer(many=True, read_only=True)
    season_name = serializers.SerializerMethodField()
    tournament_name = serializers.SerializerMethodField()
    winner_name = serializers.CharField(source="winner.name", read_only=True)
    league = serializers.SerializerMethodField()
    league_name = serializers.SerializerMethodField()
    team_count = serializers.SerializerMethodField()
    matches = serializers.SerializerMethodField()

    class Meta:
        model = Bracket
        fields = ['id', 'league', 'league_name', 'season', 'season_name', 'tournament', 'tournament_name', 'team_count', 'elimination_type', 'winner', 'winner_name', 'is_complete', 'created_at', 'updated_at', 'rounds', 'matches']
        read_only_fields = ["winner", "team_count", "is_complete"]

    def get_season_name(self, obj):
        return obj.season.name if obj.season else None

    def get_tournament_name(self, obj):
        return obj.tournament.name if obj.tournament else None

    def get_league_name(self, obj):
        if obj.season and obj.season.league:
            return obj.season.league.name
        elif obj.tournament:
            return None  # Tournaments don't have leagues
        return None

    def get_league(self, obj):
        if obj.season and obj.season.league:
            return obj.season.league.id
        elif obj.tournament:
            return None  # Tournaments don't have leagues
        return None
    
    def create(self, validated_data):
        """Create bracket and trigger generation in the viewset"""
        # Validate that only one of season or tournament is provided
        season = validated_data.get('season')
        tournament = validated_data.get('tournament')
        
        if season and tournament:
            raise serializers.ValidationError("A bracket cannot be associated with both a season and a tournament. Please provide only one.")
        
        if not season and not tournament:
            raise serializers.ValidationError("A bracket must be associated with either a season or a tournament.")
        
        bracket = Bracket.objects.create(**validated_data)
        return bracket
    
    def validate(self, data):
        """Validate that only one of season or tournament is provided"""
        season = data.get('season')
        tournament = data.get('tournament')
        
        if season and tournament:
            raise serializers.ValidationError("A bracket cannot be associated with both a season and a tournament. Please provide only one.")
        
        if not season and not tournament:
            raise serializers.ValidationError("A bracket must be associated with either a season or a tournament.")
        
        return data
    
    def get_team_count(self, obj):
        return obj.team_count()
    
    def get_matches(self, obj):
        """Format matches for frontend bracket display"""
        if obj.elimination_type == 'double':
            return self._format_double_elimination(obj)
        elif obj.elimination_type == 'single':
            return self._format_single_elimination(obj)
        return None
    
    def _format_double_elimination(self, bracket):
        """Format double elimination matches for @g-loot/react-tournament-brackets"""
        all_matches = BracketMatch.objects.filter(bracket=bracket).select_related(
            'home_team', 'away_team', 'winner', 'game', 'round'
        ).order_by('round__round_number', 'id')
        
        # Determine which rounds are upper bracket and which are lower
        total_teams = bracket.team_count()
        # Calculate based on next power of 2 to match generator logic
        next_power_of_2 = 1 << (total_teams - 1).bit_length()
        upper_rounds_count = (next_power_of_2 - 1).bit_length()
        lower_rounds_count = 2 * (upper_rounds_count - 1)
        
        upper_matches = []
        lower_matches = []
        
        for match in all_matches:
            formatted_match = self._format_match_for_frontend(match)
            
            # Determine if this is upper or lower bracket based on round number
            if match.round.round_number <= upper_rounds_count:
                # Upper bracket
                upper_matches.append(formatted_match)
            elif match.round.round_number <= upper_rounds_count + lower_rounds_count:
                # Lower bracket
                lower_matches.append(formatted_match)
            else:
                # Grand final - add to upper bracket
                upper_matches.append(formatted_match)
        
        return {
            'upper': upper_matches,
            'lower': lower_matches
        }
    
    def _format_single_elimination(self, bracket):
        """Format single elimination matches for @g-loot/react-tournament-brackets"""
        all_matches = BracketMatch.objects.filter(bracket=bracket).select_related(
            'home_team', 'away_team', 'winner', 'game', 'round'
        ).order_by('round__round_number', 'id')
        
        return [self._format_match_for_frontend(match) for match in all_matches]
    
    def _format_match_for_frontend(self, match):
        """Convert a BracketMatch to the format expected by @g-loot/react-tournament-brackets"""
        participants = []
        
        # Format home team
        if match.home_team:
            participants.append({
                'id': f'team-{match.home_team.id}',
                'resultText': 'WON' if match.winner == match.home_team else 'LOST' if match.winner else '',
                'isWinner': match.winner == match.home_team if match.winner else False,
                'status': 'PLAYED' if match.winner else 'SCHEDULED',
                'name': match.home_team.name,
                'logo': match.home_team.logo.url if match.home_team.logo else None,
            })
        
        # Format away team
        if match.away_team:
            participants.append({
                'id': f'team-{match.away_team.id}',
                'resultText': 'WON' if match.winner == match.away_team else 'LOST' if match.winner else '',
                'isWinner': match.winner == match.away_team if match.winner else False,
                'status': 'PLAYED' if match.winner else 'SCHEDULED',
                'name': match.away_team.name,
                'logo': match.away_team.logo.url if match.away_team.logo else None,
            })
        
        return {
            'id': match.id,
            'name': f'Round {match.round.round_number} Match {match.id}',
            'nextMatchId': match.next_match.id if match.next_match else None,
            'nextLooserMatchId': match.next_loser_match.id if match.next_loser_match else None,
            'startTime': match.game.date.isoformat() if match.game and match.game.date else None,
            'state': 'DONE' if match.winner else 'SCHEDULED',
            'participants': participants,
            'isFiller': match.is_filler,  # Add filler flag for frontend
        }
