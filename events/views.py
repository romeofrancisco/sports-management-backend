from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Event
from .serializers import EventSerializer, GameEventSerializer, TrainingEventSerializer
from games.models import Game
from trainings.models import TrainingSession
from teams.models import Coach
from teams.models import Team
from django.db.models import Q
from users.models import User
from datetime import datetime
from django.utils import timezone
from dateutil import parser



class EventViewSet(viewsets.ModelViewSet):
    """
    Unified event manager endpoint combining Events, Games, and TrainingSessions.
    """

    queryset = Event.objects.all().order_by("-startDate")
    serializer_class = EventSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return events filtered by the requesting user's role."""
        user = self.request.user

        # Admin sees all events
        if getattr(user, "is_admin", False):
            return Event.objects.all()

        # Coach - events created by self or by admins
        if getattr(user, "is_coach", False) or hasattr(user, "coach_profile"):
            return Event.objects.filter(
                Q(created_by__role=User.Role.ADMIN) | Q(created_by=user)
            ).distinct()

        # Player/other users - events created by admins or coaches of their teams
        teams = Team.objects.filter(players__user=user)

        # Coaches of the player's teams
        coach_ids = Coach.objects.filter(
            Q(head_coached_teams__in=teams) | Q(assistant_coached_teams__in=teams)
        ).values_list("user_id", flat=True).distinct()

        return Event.objects.filter(
            Q(created_by__role=User.Role.ADMIN) | Q(created_by__id__in=coach_ids)
        ).distinct()

    def list(self, request, *args, **kwargs):
        """Return combined Event, Game, and TrainingSession events."""
        user = request.user

        # Filter events via get_queryset()
        events_qs = self.get_queryset()

        # Filter games/trainings based on user role
        if getattr(user, "is_admin", False):
            games_qs = Game.objects.all()
            trainings_qs = TrainingSession.objects.all()
        elif getattr(user, "is_coach", False) or hasattr(user, "coach_profile"):
            coach_profile = getattr(user, "coach_profile", None)
            coach_teams = Team.objects.filter(
                Q(head_coach=coach_profile) | Q(assistant_coach=coach_profile)
            )
            games_qs = Game.objects.filter(
                Q(home_team__in=coach_teams) | Q(away_team__in=coach_teams)
            )
            trainings_qs = TrainingSession.objects.filter(team__in=coach_teams)
        else:
            # Player
            teams = Team.objects.filter(players__user=user)
            games_qs = Game.objects.filter(Q(home_team__in=teams) | Q(away_team__in=teams))
            trainings_qs = TrainingSession.objects.filter(team__in=teams)

        # Serialize
        events_data = EventSerializer(events_qs, many=True).data
        games_data = GameEventSerializer(games_qs, many=True).data
        trainings_data = TrainingEventSerializer(trainings_qs, many=True).data

        # Combine
        combined = events_data + games_data + trainings_data

        # Safe sorting by startDate
        def safe_parse(date_value):
            """Convert string or datetime to aware datetime for sorting."""
            if isinstance(date_value, datetime):
                # Ensure aware
                if timezone.is_naive(date_value):
                    return timezone.make_aware(date_value, timezone.get_current_timezone())
                return date_value
            if isinstance(date_value, str):
                try:
                    dt = parser.isoparse(date_value)  # automatically handles Z / offset
                    if timezone.is_naive(dt):
                        dt = timezone.make_aware(dt, timezone.get_current_timezone())
                    return dt
                except Exception:
                    return timezone.make_aware(datetime.max)
            return timezone.make_aware(datetime.max)

        combined.sort(key=lambda e: safe_parse(e.get("startDate")), reverse=False)

        return Response(combined)

    def perform_create(self, serializer):
        """Assign creator when creating a new Event."""
        serializer.save(created_by=self.request.user)
