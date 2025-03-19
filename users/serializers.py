from rest_framework.serializers import ModelSerializer, Serializer
from .models import User
from rest_framework import serializers
from django.contrib.auth import authenticate


class UserSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ( "profile", "first_name", "last_name", "email", "role", "date_of_birth")


class RegisterPlayerSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "profile", "first_name", "last_name", "email", "password")
        extra_kwargs = {"password": {"write_only": True}}
        read_only_fields = ("id",)

    def create(self, validated_data):
        user = User.objects.create_player(**validated_data)
        return user


class RegisterCoachSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ("profile", "first_name", "last_name", "email", "password")
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
