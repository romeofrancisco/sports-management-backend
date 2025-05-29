from rest_framework.serializers import ModelSerializer, Serializer
from rest_framework import serializers
from .models import Team, Player, Coach
from users.serializers import PlayerSerializer, CoachSerializer
from sports.models import Sport, Position
from sports.serializers import SportSerializer, PositionSerializer


class TeamSerializer(ModelSerializer):
    logo = serializers.ImageField(use_url=True, required=False)
    coach_name = serializers.SerializerMethodField()
    coach_id = serializers.IntegerField(source="coach.user.id", read_only=True, allow_null=True)
    sport_name = serializers.CharField(source="sport.name", read_only=True)
    player_count = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = "__all__"
        read_only_fields = ("created_at", "slug")

    def get_coach_name(self, obj):
        if obj.coach and obj.coach.user:
            return f"{obj.coach.user.first_name} {obj.coach.user.last_name}"
        return None

    def get_player_count(self, obj):
        return obj.players.count()

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
    teams = TeamSerializer(many=True, read_only=True) 
    
    full_name = serializers.SerializerMethodField()
    class Meta:
        model = Coach
        fields = ["id", "profile", "first_name", "last_name", "full_name", "sex", "email", "password", "teams"]
        
    def get_full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only require password on creation
        if self.instance is not None:
            self.fields["password"].required = False

    def create(self, validated_data):
        user_data = validated_data.pop("user")

        # Create the User instance using the nested serializer
        user_serializer = CoachSerializer(data=user_data)
        user_serializer.is_valid(raise_exception=True)  # Ensures data is valid
        user = user_serializer.save()

        # Create the Player instance with the user instance
        coach = Coach.objects.create(user=user, **validated_data)
        return coach
    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})
        user = instance.user

        # Update the User model
        for attr, value in user_data.items():
            if attr == "password":
                user.set_password(value)
            else:
                setattr(user, attr, value)
        user.save()

        # Update the Coach model
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        return instance