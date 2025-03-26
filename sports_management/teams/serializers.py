from rest_framework.serializers import ModelSerializer, Serializer
from rest_framework import serializers
from .models import Team, Player, Coach
from users.serializers import PlayerSerializer, CoachSerializer
from sports.models import Position, Sport
from sports.serializers import PositionSerializer, SportSerializer


class TeamSerializer(ModelSerializer):
    logo = serializers.ImageField(use_url=True)
    record = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = "__all__"
        read_only_fields = ("created_at", "slug")

    def get_record(self, obj):
        wins, losses = obj.record()
        return {"win": wins, "loss": losses}
    
    def validate_coach(self, value):
        if not value: 
            raise serializers.ValidationError("At least one coach is required.")
        return value


class PlayerInfoSerializer(ModelSerializer):
    id = serializers.IntegerField(source="user.id", read_only=True)
    profile = serializers.ImageField(source="user.profile")
    first_name = serializers.CharField(source="user.first_name", required=True)
    last_name = serializers.CharField(source="user.last_name", required=True)
    email = serializers.EmailField(source="user.email", required=True)
    password = serializers.CharField(source="user.password", required=True, write_only=True)

    team_id = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all(), write_only=True)
    position_ids = serializers.PrimaryKeyRelatedField(queryset=Position.objects.all(), many=True, write_only=True)
    sport_id = serializers.PrimaryKeyRelatedField(queryset=Sport.objects.all(), write_only=True)
    
    team = TeamSerializer(read_only=True)
    positions = PositionSerializer(many=True, read_only=True, source="position")
    sport = SportSerializer(read_only=True)

    class Meta:
        model = Player
        fields = [
            "id",
            "profile",
            "first_name",
            "last_name",
            "email",
            "password",
            "slug",
            "height",
            "weight",
            "team_id",  # POST
            "team",  # GET
            "jersey_number",
            "position_ids",  # POST
            "positions",  # GET
            "sport_id",  # POST
            "sport",  # GET
        ]
        
        
    def validate_position_ids(self, value):
        if not value:  # If the list is empty
            raise serializers.ValidationError("At least one position is required.")
        return value

    def get_sport(self, obj):
        return SportSerializer(obj.sport).data if obj.sport else None

    def get_team(self, obj):
        return TeamSerializer(obj.team).data if obj.team else None

    def create(self, validated_data):
        # Extract user data from validated_data (under 'user' key due to source)
        user_data = validated_data.pop("user", {})
        team = validated_data.pop("team_id", None)
        positions = validated_data.pop("position_ids", [])
        sport = validated_data.pop("sport_id", None)

        # Create User using PlayerSerializer
        user_serializer = PlayerSerializer(data=user_data)
        user_serializer.is_valid(raise_exception=True)
        user = user_serializer.save()

        # Create Player instance
        player = Player.objects.create(
            user=user, team=team, sport=sport, **validated_data
        )
        player.position.set(positions)
        return player

    def update(self, instance, validated_data):
        # Extract nested and related data from validated_data
        user_data = validated_data.pop("user", {})
        team = validated_data.pop("team_id", None)
        positions = validated_data.pop("position_ids", None)
        sport = validated_data.pop("sport_id", None)

        # Update User if data exists
        if user_data:
            user_serializer = PlayerSerializer(
                instance.user, 
                data=user_data, 
                partial=True  # Allow partial updates
            )
            user_serializer.is_valid(raise_exception=True)
            user_serializer.save()

        # Update direct relationships
        if team is not None:
            instance.team = team
        if sport is not None:
            instance.sport = sport
        if positions is not None:
            instance.position.set(positions)

        # Let ModelSerializer handle remaining fields (height, weight, jersey_number, etc.)
        instance = super().update(instance, validated_data)

        return instance


class CoachSerializer(ModelSerializer):
    id = serializers.IntegerField(source="user.id", read_only=True)
    profile = serializers.ImageField(source="user.profile")
    first_name = serializers.CharField(source="user.first_name")
    last_name = serializers.CharField(source="user.last_name")
    email = serializers.CharField(source="user.email")
    password = serializers.CharField(source="user.password", write_only=True)

    class Meta:
        model = Coach
        fields = ["id", "profile", "first_name", "last_name", "email", "password"]

    def create(self, validated_data):
        user_data = validated_data.pop("user")

        # Create the User instance using the nested serializer
        user_serializer = CoachSerializer(data=user_data)
        user_serializer.is_valid(raise_exception=True)  # Ensures data is valid
        user = user_serializer.save()

        # Create the Player instance with the user instance
        coach = Coach.objects.create(user=user, **validated_data)
        return coach