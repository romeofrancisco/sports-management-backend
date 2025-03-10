from rest_framework.serializers import ModelSerializer
from .models import Team, Player, Coach
from users.serializers import RegisterPlayerSerializer, RegisterCoachSerializer


class TeamSerializer(ModelSerializer):
    class Meta:
        model = Team
        fields = "__all__"
        read_only_fields = ("created_at",)


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
        fields = ["user", "sports", "teams"]

    def create(self, validated_data):
        user_data = validated_data.pop("user")
        
        # Create the User instance using the nested serializer
        user_serializer = RegisterCoachSerializer(data=user_data)
        user_serializer.is_valid(raise_exception=True)  # Ensures data is valid
        user = user_serializer.save()
        
        # Extract teams and positions from validated_data
        teams = validated_data.pop("teams", [])
        sports = validated_data.pop("sports", [])

        # Create the Player instance with the user instance
        coach = Coach.objects.create(user=user, **validated_data)
        coach.teams.set(teams)
        coach.sports.set(sports)
        return coach
