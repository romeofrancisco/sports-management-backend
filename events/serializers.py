from rest_framework import serializers
from django.utils import timezone
from .models import Event
from rest_framework import serializers
from django.utils import timezone
from datetime import datetime, time, timedelta
from games.models import Game
from trainings.models import TrainingSession

class TrainingEventSerializer(serializers.ModelSerializer):
    startDate = serializers.SerializerMethodField()
    endDate = serializers.SerializerMethodField()
    color = serializers.SerializerMethodField()
    user = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()
    id = serializers.SerializerMethodField()

    class Meta:
        model = TrainingSession
        fields = [
            "id",
            "title",
            "description",
            "startDate",
            "endDate",
            "location",
            "status",
            "user",
            "color",
            "team",
            "type"
        ]

    def _combine_datetime(self, date_obj, time_obj, default_time=None):
        if not date_obj:
            date_obj = timezone.localdate()
        if not time_obj:
            time_obj = default_time or time.min
        dt = datetime.combine(date_obj, time_obj)
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt.isoformat()
    
    def get_id(self, obj):
        return f"training:{obj.id}"
    
    def get_user(self, obj):
        user = getattr(obj, "creator", None)
        if not user:
            return {"id": f"game:{obj.id}", "name": "System"}
        
        picture = None
        try:
            profile = getattr(user, "profile", None)
            if profile and hasattr(profile, "url"):
                picture = profile.url
        except Exception:
            picture = None
        
        return {
            "id": user.id,
            "name": user.get_full_name() or user.email,
            "email": getattr(user, "email", None),
            "role": getattr(user, "role", None),
            "picture": picture,
        }

    def get_startDate(self, obj):
        return self._combine_datetime(obj.date, obj.start_time, default_time=time(9, 0))

    def get_endDate(self, obj):
        return self._combine_datetime(obj.date, obj.end_time, default_time=time(10, 0))

    def get_color(self, obj):
        return "orange"
    
    def get_type(self, obj):
        return "training"


class GameEventSerializer(serializers.ModelSerializer):
    # Frontend expects ISO datetimes for event start and end
    startDate = serializers.SerializerMethodField()
    endDate = serializers.SerializerMethodField()

    # For display consistency with EventSerializer
    title = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    user = serializers.SerializerMethodField()
    meta = serializers.SerializerMethodField()
    color = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()
    id = serializers.SerializerMethodField()

    class Meta:
        model = Game
        fields = [
            "id",
            "title",
            "description",
            "startDate",
            "endDate",
            "color",
            "status",
            "user",
            "meta",
            "type",
        ]

    # ---- Core computed fields ----
    
    def get_id(self, obj):
        return f"game:{obj.id}"
    
    def get_type(self, obj):
        return obj.type

    def get_startDate(self, obj):
        """Combine game date and time into a full datetime."""
        if obj.date:
            if obj.time:
                dt = datetime.combine(obj.date, obj.time)
            else:
                dt = datetime.combine(obj.date, time(9, 0))  # default 9:00 AM if no time
            return timezone.make_aware(dt)
        return None

    def get_endDate(self, obj):
        """Estimate game end time (e.g. +2 hours duration)."""
        start = self.get_startDate(obj)
        if start:
            duration = obj.duration or timedelta(hours=2)
            return start + duration
        return None

    def get_title(self, obj):
        """Readable game title for calendar (Team A vs Team B)."""
        return f"{obj.home_team.name} vs {obj.away_team.name}"

    def get_description(self, obj):
        """Optional detailed info."""
        parts = []
        if obj.location:
            parts.append(f"Location: {obj.location}")
        if obj.sport:
            parts.append(f"Sport: {obj.sport.name}")
        if obj.type:
            parts.append(f"Type: {obj.get_type_display()}")
        if obj.league:
            parts.append(f"League: {obj.league.name}")
        if obj.season:
            parts.append(f"Season: {obj.season.name}")
        return " | ".join(parts) or "Game Event"

    def get_user(self, obj):
        """Represent game creator as 'user' for compatibility."""
        user = getattr(obj, "creator", None)
        if not user:
            return {"id": f"game:{obj.id}", "name": "System"}
        
        picture = None
        try:
            profile = getattr(user, "profile", None)
            if profile and hasattr(profile, "url"):
                picture = profile.url
        except Exception:
            picture = None
        
        return {
            "id": user.id,
            "name": user.get_full_name() or user.email,
            "email": getattr(user, "email", None),
            "role": getattr(user, "role", None),
            "picture": picture,
        }

    def get_color(self, obj):
        match obj.type:
            case 'practice':
                return "green"
            case 'tournament':
                return "purple"
            case 'league':
                return "red"


    def get_meta(self, obj):
        """Attach meta data useful for frontend filters."""
        return {
            "status": obj.status,
            "type": obj.type,
            "sport": getattr(obj.sport, "name", None),
            "league": getattr(obj.league, "name", None),
            "season": getattr(obj.season, "name", None),
            "home_team": getattr(obj.home_team, "name", None),
            "away_team": getattr(obj.away_team, "name", None),
            "winner": getattr(obj.winner_team, "name", None),
        }



class EventSerializer(serializers.ModelSerializer):
    # Model now stores datetimes directly; use DRF DateTimeField so DRF will
    # parse incoming ISO datetimes and render ISO datetimes on output.
    startDate = serializers.DateTimeField()
    endDate = serializers.DateTimeField()
    # Provide a lightweight `user` object for frontend filters (events are not tied to users here)
    user = serializers.SerializerMethodField()
    # Arbitrary meta object carrying status/location for frontend use
    meta = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()
    color = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            "id",
            "title",
            "description",
            "startDate",  # ISO datetime string for the frontend
            "endDate",    # ISO datetime string for the frontend
            "color",
            "status",
            "user",
            "meta",
            "type",
        ]
        read_only_fields = ["id"]

    # startDate and endDate are DateTimeFields on the model; DRF will handle
    # serialization to ISO 8601 strings automatically. No manual combining is needed.

    def get_type(self, obj):
        return 'event'
    
    def get_color(self, obj):
        return "blue"

    def get_user(self, obj):
        # If the event was created by a user, expose a lightweight user object
        # for the frontend. Otherwise fall back to a synthetic event owner object
        # (keeps backward compatibility with older clients).
        user = getattr(obj, "created_by", None)
        if not user:
            return {"id": f"event:{obj.id}", "name": obj.title}

        # Try to get a public profile URL if available (ImageField may be None)
        picture = None
        try:
            profile = getattr(user, "profile", None)
            if profile and hasattr(profile, "url"):
                picture = profile.url
        except Exception:
            picture = None

        return {
            "id": user.id,
            "name": user.get_full_name() or user.email,
            "email": getattr(user, "email", None),
            "role": getattr(user, "role", None),
            "picture": picture,
        }

    def get_meta(self, obj):
        return {"status": obj.status}
