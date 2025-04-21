from rest_framework.serializers import ModelSerializer
from .models import Sport, Position, SportStatType
from rest_framework import serializers


class SportSerializer(ModelSerializer):
    class Meta:
        model = Sport
        fields = "__all__"
        read_only_fields = ("created_at", "slug")


class SportStatTypeSerializer(serializers.ModelSerializer):
    sport = serializers.SlugRelatedField(
        queryset=Sport.objects.all(), slug_field="slug"
    )

    class Meta:
        model = SportStatType
        fields = "__all__"


class PositionSerializer(ModelSerializer):
    sport = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=Sport.objects.all()
    )

    class Meta:
        model = Position
        fields = "__all__"

    def validate(self, attrs):
        sport = attrs.get("sport") or getattr(self.instance, "sport", None)
        name = attrs.get("name") or getattr(self.instance, "name", None)
        abbreviation = attrs.get("abbreviation") or getattr(
            self.instance, "abbreviation", None
        )

        # Validate name uniqueness per sport
        qs_name = Position.objects.filter(sport=sport, name=name)
        if self.instance:
            qs_name = qs_name.exclude(pk=self.instance.pk)
        if qs_name.exists():
            raise serializers.ValidationError(
                {"name": "This name is already used for this sport."}
            )

        # Validate abbreviation uniqueness per sport (only if provided)
        if abbreviation:
            qs_abbr = Position.objects.filter(sport=sport, abbreviation=abbreviation)
            if self.instance:
                qs_abbr = qs_abbr.exclude(pk=self.instance.pk)
            if qs_abbr.exists():
                raise serializers.ValidationError(
                    {
                        "abbreviation": "This abbreviation is already used for this sport."
                    }
                )

        return attrs

