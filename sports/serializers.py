from rest_framework.serializers import ModelSerializer
from .models import Sport, Position


class SportSerializer(ModelSerializer):
    class Meta:
        model = Sport
        fields = "__all__"
        read_only_fields = ("created_at",)

class PositionSerializer(ModelSerializer):
    class Meta:
        model = Position
        fields = "__all__"

