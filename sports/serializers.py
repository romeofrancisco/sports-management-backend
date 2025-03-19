from rest_framework.serializers import ModelSerializer
from .models import Sport, Position, SportStatType

class SportSerializer(ModelSerializer):
    class Meta:
        model = Sport
        fields = "__all__"
        read_only_fields = ("created_at", "slug")

class SportStatTypeSerializer(ModelSerializer):
    class Meta:
        model = SportStatType
        fields = '__all__'

class PositionSerializer(ModelSerializer):
    class Meta:
        model = Position
        fields = "__all__"



