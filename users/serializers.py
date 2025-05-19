from rest_framework.serializers import ModelSerializer, Serializer
from .models import User
from rest_framework import serializers
from django.contrib.auth import authenticate


class UserSerializer(ModelSerializer):
    team_id = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = User
        fields = (
            "profile",
            "first_name",
            "last_name",
            "sex",
            "email",
            "role",
            "date_of_birth",
            "team_id",
        )
    
    def get_team_id(self, obj):
        if hasattr(obj, 'coach_profile'):
            # Get team coached by this coach
            team = obj.coach_profile.teams.first()
            return team.id if team else None
        elif hasattr(obj, 'player_profile'):
            return obj.player_profile.team_id if obj.player_profile.team else None
        return None


class PlayerSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "profile", "first_name", "last_name", "sex", "email", "password")
        extra_kwargs = {"password": {"write_only": True}}
        read_only_fields = ("id",)

    def create(self, validated_data):
        user = User.objects.create_player(**validated_data)
        return user


class CoachSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "profile", "first_name", "last_name", "sex", "email", "password")
        extra_kwargs = {"password": {"write_only": True}}

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
