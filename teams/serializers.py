from rest_framework.serializers import ModelSerializer, Serializer
from rest_framework import serializers
from .models import Team, Player, Coach
from users.serializers import PlayerSerializer, CoachSerializer
from sports.models import Sport, Position
from sports.serializers import SportSerializer, PositionSerializer
# Import Game model for the summary serializer
from games.models import Game


class GameSummarySerializer(ModelSerializer):
    """Simplified game serializer for analytics and performance data"""
    home_team_name = serializers.CharField(source="home_team.name", read_only=True)
    away_team_name = serializers.CharField(source="away_team.name", read_only=True)
    home_team_abbreviation = serializers.CharField(source="home_team.abbreviation", read_only=True)
    away_team_abbreviation = serializers.CharField(source="away_team.abbreviation", read_only=True)
    result = serializers.SerializerMethodField()
    score_summary = serializers.SerializerMethodField()
    
    class Meta:
        model = Game
        fields = [
            'id',
            'date',
            'home_team_name',
            'away_team_name', 
            'home_team_abbreviation',
            'away_team_abbreviation',
            'home_team_score',
            'away_team_score',
            'status',
            'result',
            'score_summary',
            'location'
        ]
    
    def get_result(self, obj):
        """Determine the result from the perspective of the requesting team"""
        # Get the team from context if available
        request = self.context.get('request')
        team = self.context.get('team')
        
        if not team or obj.status != Game.Status.COMPLETED:
            return None
            
        if obj.winner_team == team:
            return 'win'
        elif obj.winner_team is None:
            return 'draw'
        else:
            return 'loss'
    
    def get_score_summary(self, obj):
        """Get a formatted score summary"""
        if obj.home_team_score is not None and obj.away_team_score is not None:
            return f"{obj.home_team_score} - {obj.away_team_score}"
        return "TBD"


class SimpleTeamSerializer(ModelSerializer):
    """Simplified team serializer to avoid circular imports when used in coach info"""
    logo = serializers.ImageField(use_url=True, required=False)
    sport_name = serializers.CharField(source="sport.name", read_only=True)
    player_count = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = ['id', 'name', 'abbreviation', 'color', 'logo', 'sport_name', 'division', 'slug', 'player_count']

    def get_player_count(self, obj):
        return obj.players.count()


class TeamSerializer(ModelSerializer):
    logo = serializers.ImageField(use_url=True, required=False)
    head_coach_name = serializers.SerializerMethodField()
    assistant_coach_name = serializers.SerializerMethodField()
    head_coach_id = serializers.IntegerField(source="head_coach.user.id", read_only=True, allow_null=True)
    assistant_coach_id = serializers.IntegerField(source="assistant_coach.user.id", read_only=True, allow_null=True)
    sport_name = serializers.CharField(source="sport.name", read_only=True)
    player_count = serializers.SerializerMethodField()
    
    # Enhanced coach information
    head_coach_info = serializers.SerializerMethodField()
    assistant_coach_info = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = "__all__"
        read_only_fields = ("created_at", "slug")

    def get_head_coach_name(self, obj):
        if obj.head_coach and obj.head_coach.user:
            return f"{obj.head_coach.user.first_name} {obj.head_coach.user.last_name}"
        return None

    def get_assistant_coach_name(self, obj):
        if obj.assistant_coach and obj.assistant_coach.user:
            return f"{obj.assistant_coach.user.first_name} {obj.assistant_coach.user.last_name}"
        return None

    def get_player_count(self, obj):
        return obj.players.count()
    
    def get_head_coach_info(self, obj):
        """Return comprehensive head coach information"""
        if not obj.head_coach:
            return None
            
        coach = obj.head_coach
        user = coach.user
        
        return {
            'id': user.id,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'full_name': f"{user.first_name} {user.last_name}",
            'email': user.email,
            'sex': user.sex,
            'profile': user.profile.url if user.profile else None,
            'sports': [{'id': sport.id, 'name': sport.name, 'slug': sport.slug} for sport in coach.sports.all()],
            'head_coached_teams_count': coach.head_coached_teams.count(),
            'assistant_coached_teams_count': coach.assistant_coached_teams.count(),
        }
    
    def get_assistant_coach_info(self, obj):
        """Return comprehensive assistant coach information"""
        if not obj.assistant_coach:
            return None
            
        coach = obj.assistant_coach
        user = coach.user
        
        return {
            'id': user.id,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'full_name': f"{user.first_name} {user.last_name}",
            'email': user.email,
            'sex': user.sex,
            'profile': user.profile.url if user.profile else None,
            'sports': [{'id': sport.id, 'name': sport.name, 'slug': sport.slug} for sport in coach.sports.all()],
            'head_coached_teams_count': coach.head_coached_teams.count(),
            'assistant_coached_teams_count': coach.assistant_coached_teams.count(),
        }
    
    def validate(self, data):
        """Validate that coaches can handle the sport for this team"""
        head_coach = data.get('head_coach')
        assistant_coach = data.get('assistant_coach')
        sport = data.get('sport')
        
        # If we're updating, get current values if not provided
        if self.instance:
            head_coach = head_coach or self.instance.head_coach
            assistant_coach = assistant_coach or self.instance.assistant_coach
            sport = sport or self.instance.sport
        
        if head_coach and sport and not head_coach.can_coach_team(type('Team', (), {'sport': sport})()):
            raise serializers.ValidationError({
                'head_coach': f"Selected head coach cannot coach {sport.name} teams. Please assign a coach who handles this sport."
            })
            
        if assistant_coach and sport and not assistant_coach.can_coach_team(type('Team', (), {'sport': sport})()):
            raise serializers.ValidationError({
                'assistant_coach': f"Selected assistant coach cannot coach {sport.name} teams. Please assign a coach who handles this sport."
            })
        
        return data

class SportsTeamSerializer(Serializer):
    sport = serializers.CharField()
    teams = TeamSerializer(many=True, read_only=True)


class PlayerInfoSerializer(ModelSerializer):
    id = serializers.IntegerField(source="user.id", read_only=True)
    profile = serializers.ImageField(source="user.profile", required=False)
    first_name = serializers.CharField(source="user.first_name", required=True)
    last_name = serializers.CharField(source="user.last_name", required=True)
    sex = serializers.CharField(source="user.sex", required=True)
    slug = serializers.CharField(read_only=True)
    email = serializers.EmailField(source="user.email", required=True)
    password = serializers.CharField(source="user.password", required=True, write_only=True)

    team_id = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all(), write_only=True, required=False, allow_null=True)
    position_ids = serializers.PrimaryKeyRelatedField(queryset=Position.objects.all(), many=True, write_only=True, required=False)
    sport_slug = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=Sport.objects.all(),
        write_only=True,
        required=False,
        allow_null=True
    )

    # Read-only nested serializers
    team = TeamSerializer(read_only=True)
    positions = PositionSerializer(many=True, read_only=True, source="position")
    sport = SportSerializer(read_only=True)
    
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = Player
        fields = [
            "id",
            "profile",
            "first_name",
            "last_name",
            "full_name",
            "sex",
            "email",
            "slug",
            "year_level",
            "course",
            "password",
            "height",
            "weight",
            "team_id",
            "team",
            "jersey_number",
            "position_ids",
            "positions",
            "sport_slug",
            "sport",
        ]

    def validate_position_ids(self, value):
        if not value:
            raise serializers.ValidationError("At least one position is required.")
        return value

    def create(self, validated_data):
        user_data = validated_data.pop("user", {})
        team = validated_data.pop("team_id", None)
        positions = validated_data.pop("position_ids", [])
        sport = validated_data.pop("sport_slug", None)

        user_serializer = PlayerSerializer(data=user_data)
        user_serializer.is_valid(raise_exception=True)
        user = user_serializer.save()

        player = Player.objects.create(
            user=user, team=team, sport=sport, **validated_data
        )
        player.position.set(positions)
        return player

    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})
        team = validated_data.pop("team_id", None)
        positions = validated_data.pop("position_ids", None)
        sport = validated_data.pop("sport_slug", None)

        if user_data:
            user_serializer = PlayerSerializer(
                instance.user, data=user_data, partial=True
            )
            user_serializer.is_valid(raise_exception=True)
            user_serializer.save()

        if team is not None:
            instance.team = team
        if sport is not None:
            instance.sport = sport
        if positions is not None:
            instance.position.set(positions)

        # Only update the player model with remaining player data (not user data)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        return instance

    def get_full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"


class CoachInfoSerializer(ModelSerializer):
    id = serializers.IntegerField(source="user.id", read_only=True)
    profile = serializers.ImageField(source="user.profile", required=False)
    first_name = serializers.CharField(source="user.first_name", required=True)
    last_name = serializers.CharField(source="user.last_name", required=True)
    email = serializers.EmailField(source="user.email", required=True)
    sex = serializers.CharField(source="user.sex")
    password = serializers.CharField(source="user.password", required=True, write_only=True)

    # Combined teams field
    coached_teams = serializers.SerializerMethodField()
    # Sports handling
    sport_ids = serializers.PrimaryKeyRelatedField(
        queryset=Sport.objects.all(), 
        many=True, 
        write_only=True, 
        required=False,
        source='sports'
    )
    sports = SportSerializer(many=True, read_only=True)
    full_name = serializers.SerializerMethodField()
    team_count = serializers.SerializerMethodField()
    player_count = serializers.SerializerMethodField()

    class Meta:
        model = Coach
        fields = [
            "id", "profile", "first_name", "last_name", "full_name", "sex", "email", "password",
            "coached_teams", "sport_ids", "sports",
            "team_count", "player_count"
        ]

    def get_full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"

    def get_coached_teams(self, obj):
        # Get unique teams where coach is head or assistant
        head_teams = obj.head_coached_teams.all()
        assistant_teams = obj.assistant_coached_teams.all()
        all_teams = {team.id: team for team in list(head_teams) + list(assistant_teams)}
        return SimpleTeamSerializer(all_teams.values(), many=True, context=self.context).data

    def get_team_count(self, obj):
        head_team_ids = set(obj.head_coached_teams.values_list('id', flat=True))
        assistant_team_ids = set(obj.assistant_coached_teams.values_list('id', flat=True))
        return len(head_team_ids.union(assistant_team_ids))

    def get_player_count(self, obj):
        team_ids = set(obj.head_coached_teams.values_list('id', flat=True)).union(
            obj.assistant_coached_teams.values_list('id', flat=True)
        )
        from .models import Team
        players = set()
        for team in Team.objects.filter(id__in=team_ids):
            players.update(team.players.values_list('user_id', flat=True))
        return len(players)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only require password on creation
        if self.instance is not None:
            self.fields["password"].required = False

    def create(self, validated_data):
        user_data = validated_data.pop("user")
        sports = validated_data.pop("sports", [])

        # Create the User instance using the nested serializer
        user_serializer = CoachSerializer(data=user_data)
        user_serializer.is_valid(raise_exception=True)  # Ensures data is valid
        user = user_serializer.save()

        # Create the Coach instance with the user instance
        coach = Coach.objects.create(user=user, **validated_data)
        coach.sports.set(sports)
        return coach
        
    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})
        sports = validated_data.pop("sports", None)
        user = instance.user

        # Update the User model
        for attr, value in user_data.items():
            if attr == "password":
                user.set_password(value)
            else:
                setattr(user, attr, value)
        user.save()

        # Update sports if provided
        if sports is not None:
            instance.sports.set(sports)

        # Update the Coach model
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        return instance