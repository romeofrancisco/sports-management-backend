from rest_framework import serializers
from .models import League, Season
from teams.serializers import TeamSerializer

class LeagueSerializer(serializers.ModelSerializer):
    teams = TeamSerializer(many=True, read_only=True)
    standings = serializers.SerializerMethodField()

    class Meta:
        model = League
        fields = ['id', 'name', 'sport', 'teams', 'start_date', 'end_date', 'standings', 'created_at']
        read_only_fields = ['created_at']

    def get_standings(self, obj):
        return obj.standings

class LeagueWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = League
        fields = ['name', 'sport', 'start_date', 'end_date', 'teams']

class SeasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Season
        fields = '__all__'
        read_only_fields = ['league']

    def validate(self, data):
        if data['start_date'] >= data['end_date']:
            raise serializers.ValidationError(
                "End date must be after start date"
            )
        return data