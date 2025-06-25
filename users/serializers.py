from rest_framework.serializers import ModelSerializer, Serializer
from .models import User
from rest_framework import serializers
from django.contrib.auth import authenticate
from teams.models import Player, Team


class UserSerializer(ModelSerializer):
    profile = serializers.SerializerMethodField()
    team_slug = serializers.SerializerMethodField()
    
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
            "team_slug",
        )
    
    def get_profile(self, obj):
        if obj.profile:
            request = self.context.get('request')
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


class PlayerSerializer(ModelSerializer):
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
            "password",
        )
        extra_kwargs = {"password": {"write_only": True}}
        read_only_fields = ("id",)

    def get_profile(self, obj):
        if obj.profile:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile.url)
            return obj.profile.url
        return None

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
            "password",
        )
        extra_kwargs = {"password": {"write_only": True}}

    def get_profile(self, obj):
        if obj.profile:
            request = self.context.get('request')
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
