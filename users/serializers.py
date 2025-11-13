from rest_framework.serializers import ModelSerializer, Serializer
from .models import User
from rest_framework import serializers
from django.contrib.auth import authenticate
from teams.models import Player, Team


class UserProfileUpdateSerializer(ModelSerializer):
    """Serializer for updating user profile information"""

    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "email",
            "sex",
            "date_of_birth",
            "phone_number",
            "profile",
        )

    def validate_email(self, value):
        user = self.instance
        if User.objects.exclude(pk=user.pk).filter(email=value).exists():
            raise serializers.ValidationError("This email is already in use.")
        return value


class UserSerializer(ModelSerializer):
    profile = serializers.SerializerMethodField()
    team_slug = serializers.SerializerMethodField()
    player_details = serializers.SerializerMethodField()
    coach_details = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "profile",
            "first_name",
            "last_name",
            "sex",
            "email",
            "role",
            "date_of_birth",
            "phone_number",
            "team_slug",
            "player_details",
            "coach_details",
        )
        read_only_fields = ("id", "role")

    def get_profile(self, obj):
        if obj.profile:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.profile.url)
            return obj.profile.url
        return None

    def get_team_slug(self, obj):
        try:
            player = Player.objects.get(user=obj)
            if player.team:
                return player.team.slug
        except Player.DoesNotExist:
            return None
        return None

    def get_player_details(self, obj):
        try:
            from teams.serializers import PlayerSerializer

            player = Player.objects.get(user=obj)
            academic_info = player.academic_info
            return {
                "height": player.height,
                "weight": player.weight,
                "jersey_number": player.jersey_number,
                "academic_info": {
                    "id": academic_info.id if academic_info else None,
                    "year_level": academic_info.year_level if academic_info else None,
                    "course": academic_info.course if academic_info else None,
                    "section": academic_info.section if academic_info else None,
                } if academic_info else None,
                "team_id": player.team.id if player.team else None,
                "team_name": player.team.name if player.team else None,
                "sport_id": player.sport.id if player.sport else None,
                "sport_name": player.sport.name if player.sport else None,
            }
        except Player.DoesNotExist:
            return None

    def get_coach_details(self, obj):
        try:
            from teams.models import Coach

            coach = Coach.objects.get(user=obj)
            return {
                "sports": [
                    {"id": sport.id, "name": sport.name} for sport in coach.sports.all()
                ]
            }
        except Coach.DoesNotExist:
            return None


class PlayerSerializer(ModelSerializer):
    profile = serializers.ImageField(required=False)
    class Meta:
        model = User
        fields = (
            "id",
            "profile",
            "first_name",
            "last_name",
            "sex",
            "email",
        )
        read_only_fields = ("id",)

    def create(self, validated_data):
        user = User.objects.create_player(**validated_data)
        return user


class CoachSerializer(ModelSerializer):
    profile = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "profile",
            "first_name",
            "last_name",
            "sex",
            "email",
        )

    def get_profile(self, obj):
        if obj.profile:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.profile.url)
            return obj.profile.url
        return None

    def create(self, validated_data):
        user = User.objects.create_coach(**validated_data)
        return user


class LoginUserSerializer(Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(**data)
        if user and user.is_active:
            return user
        raise serializers.ValidationError("Incorrect credentials!")
