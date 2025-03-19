from rest_framework.serializers import ModelSerializer, Serializer
from rest_framework import serializers
from .models import Team, Player, Coach
from users.serializers import RegisterPlayerSerializer, RegisterCoachSerializer

class TeamSerializer(ModelSerializer):
    class Meta:
        model = Team
        fields = "__all__"
        read_only_fields = ("created_at", "slug")
    
    def get_logo(self, obj):
        request = self.context.get("request")
        if obj.logo:
            return request.build_absolute_uri(obj.logo.url) if request else obj.logo.url
        return None
    
    def to_representation(self, instance):
        rep = super().to_representation(instance)
        wins, losses = instance.win_loss_record()
        rep["win"] = wins
        rep["loss"] = losses
        return rep

class SportsTeamSerializer(Serializer):
    sport = serializers.CharField()
    teams = TeamSerializer(many=True, read_only=True)
    
class PlayerSerializer(ModelSerializer):
    user = RegisterPlayerSerializer()

    class Meta:
        model = Player
        fields = ["user", "height", "weight", "team", "jersey_number", "position", "sport"]

    def create(self, validated_data):
        user_data = validated_data.pop("user")
        
        # Create the User instance using the nested serializer
        user_serializer = RegisterPlayerSerializer(data=user_data)
        user_serializer.is_valid(raise_exception=True)  # Ensures data is valid
        user = user_serializer.save()

        # Create the Player instance with the user instance
        player = Player.objects.create(user=user, **validated_data)
        return player
    
    
class CoachSerializer(ModelSerializer):
    user = RegisterCoachSerializer()

    class Meta:
        model = Coach
        fields = ["user", "sports"]

    def create(self, validated_data):
        user_data = validated_data.pop("user")
        
        # Create the User instance using the nested serializer
        user_serializer = RegisterCoachSerializer(data=user_data)
        user_serializer.is_valid(raise_exception=True)  # Ensures data is valid
        user = user_serializer.save()

        # Create the Player instance with the user instance
        coach = Coach.objects.create(user=user, **validated_data)
        return coach
