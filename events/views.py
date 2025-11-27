from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Q
from datetime import datetime, timedelta
from dateutil import parser
from .models import Event
from games.models import Game
from trainings.models import TrainingSession
from teams.models import Team
from teams.models import Coach
from users.models import User
from .serializers import EventSerializer, GameEventSerializer, TrainingEventSerializer
from notifications.utils import send_event_notification
import calendar

class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all().order_by("-startDate")
    serializer_class = EventSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        """Create event and send notifications based on creator's role."""
        event = serializer.save(created_by=self.request.user)
        
        # Send notification asynchronously
        try:
            send_event_notification(event, creator=self.request.user)
        except Exception:
            pass  # Don't fail the request if notification fails

    def get_queryset(self):
        user = self.request.user

        if getattr(user, "is_admin", False):
            return Event.objects.all()

        if getattr(user, "is_coach", False) or hasattr(user, "coach_profile"):
            return Event.objects.filter(
                Q(created_by__role=User.Role.ADMIN) | Q(created_by=user)
            ).distinct()

        teams = Team.objects.filter(players__user=user)
        coach_ids = Coach.objects.filter(
            Q(head_coached_teams__in=teams) | Q(assistant_coached_teams__in=teams)
        ).values_list("user_id", flat=True).distinct()

        return Event.objects.filter(
            Q(created_by__role=User.Role.ADMIN) | Q(created_by__id__in=coach_ids)
        ).distinct()

    def list(self, request, *args, **kwargs):
        user = request.user
        view_type = request.query_params.get("view", "month").lower()
        date_str = request.query_params.get("date")

        # Default to current date if not provided
        if date_str:
            try:
                selected_date = parser.parse(date_str)
            except Exception:
                selected_date = timezone.now()
        else:
            selected_date = timezone.now()

        # Ensure timezone awareness
        if timezone.is_naive(selected_date):
            selected_date = timezone.make_aware(selected_date, timezone.get_current_timezone())

        # Compute date range based on view type
        if view_type == "day":
            start = selected_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif view_type == "week":
            start = selected_date - timedelta(days=selected_date.weekday())  # Monday start
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
        elif view_type in ["month", "agenda"]:
            start = selected_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_day = calendar.monthrange(start.year, start.month)[1]
            end = start.replace(day=last_day, hour=23, minute=59, second=59)
        elif view_type == "year":
            start = selected_date.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end = selected_date.replace(month=12, day=31, hour=23, minute=59, second=59)
        else:
            start = selected_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_day = calendar.monthrange(start.year, start.month)[1]
            end = start.replace(day=last_day, hour=23, minute=59, second=59)

        # Filter datasets directly in DB
        events_qs = self.get_queryset().filter(startDate__range=(start, end))

        if getattr(user, "is_admin", False):
            games_qs = Game.objects.filter(started_at__range=(start, end))
            trainings_qs = TrainingSession.objects.filter(date__range=(start.date(), end.date()))
        elif getattr(user, "is_coach", False) or hasattr(user, "coach_profile"):
            coach_profile = getattr(user, "coach_profile", None)
            coach_teams = Team.objects.filter(
                Q(head_coach=coach_profile) | Q(assistant_coach=coach_profile)
            )
            games_qs = Game.objects.filter(
                Q(home_team__in=coach_teams) | Q(away_team__in=coach_teams),
                started_at__range=(start, end),
            )
            trainings_qs = TrainingSession.objects.filter(
                team__in=coach_teams, date__range=(start.date(), end.date())
            )
        else:
            teams = Team.objects.filter(players__user=user)
            games_qs = Game.objects.filter(
                Q(home_team__in=teams) | Q(away_team__in=teams),
                started_at__range=(start, end),
            )
            trainings_qs = TrainingSession.objects.filter(
                team__in=teams, date__range=(start.date(), end.date())
            )

        # Serialize all
        events_data = EventSerializer(events_qs.order_by("startDate"), many=True).data
        games_data = GameEventSerializer(games_qs.order_by("started_at"), many=True).data
        trainings_data = TrainingEventSerializer(trainings_qs.order_by("date"), many=True).data

        # Merge results
        combined = events_data + games_data + trainings_data
        
        # Safe parse helper

        def safe_parse_date(item):
            """
            Safely parse possible date keys into a comparable datetime.
            Accepts ISO strings or datetime objects.
            """
            value = item.get("startDate") or item.get("started_at") or item.get("date")
            if not value:
                return timezone.now()  # fallback

            # Handle datetime objects directly
            if isinstance(value, datetime):
                if timezone.is_naive(value):
                    return timezone.make_aware(value, timezone.get_current_timezone())
                return value

            # Handle string values
            try:
                dt = parser.isoparse(str(value))
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                return dt
            except Exception:
                return timezone.now()

        # Sort safely by datetime value
        combined.sort(key=lambda e: safe_parse_date(e), reverse=False)

        # Normalize all date fields to string for response consistency
        for item in combined:
            for key in ["startDate", "endDate", "started_at", "ended_at", "date"]:
                if key in item and isinstance(item[key], datetime):
                    item[key] = item[key].isoformat()


        return Response(sorted(combined, key=lambda e: e.get("startDate", e.get("started_at", e.get("date")))))