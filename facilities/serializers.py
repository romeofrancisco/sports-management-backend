from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import Facility, Reservation
from users.models import User


class FacilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Facility
        fields = [
            "id",
            "name",
            "description",
            "image",
            "location",
            "capacity",
            "is_active",
            "created_at",
            "updated_at",
        ]


class ReservationSerializer(serializers.ModelSerializer):
    facility = FacilitySerializer(read_only=True)
    facility_id = serializers.PrimaryKeyRelatedField(
        queryset=Facility.objects.all(), source="facility", write_only=True
    )
    coach_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.COACH),
        source="coach",
        required=False,
        write_only=True,
    )
    coach = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Reservation
        fields = [
            "id",
            "facility",
            "facility_id",
            "coach",
            "coach_id",
            "requested_by",
            "start_datetime",
            "end_datetime",
            "status",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["requested_by", "created_at", "updated_at"]

    def get_coach(self, obj):
        if obj.coach:
            return {
                "id": obj.coach.id,
                "name": obj.coach.get_full_name(),
                "email": obj.coach.email,
                "profile": obj.coach.profile.url if obj.coach.profile else None,
            }
        return None

    def validate(self, attrs):
        # start/end validation
        start = attrs.get("start_datetime")
        end = attrs.get("end_datetime")
        if start and end and end <= start:
            # Return a field-specific error so the frontend can attach it
            # to the `endDate` / `end_datetime` form field instead of
            # sending a non-field error.
            raise serializers.ValidationError(
                {"end_datetime": ["End time must be after start time"]}
            )
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        user = request.user if request else None

        # Allow callers to explicitly supply `requested_by` (e.g. scripts),
        # but prefer the authenticated request user when available.
        requested_by = validated_data.pop("requested_by", None)

        facility = validated_data.pop("facility")
        coach = validated_data.pop("coach", None)

        # If user is a coach, they are the coach for the reservation
        # If user is a coach, they are the coach for the reservation.
        # If an admin creates a reservation and does not supply a coach_id,
        # treat the admin as the coach (they're reserving for themselves).
        if user:
            if user.is_coach:
                coach = user
            elif user.is_admin and not coach:
                coach = user

        # Determine the final requested_by: prefer explicitly provided value,
        # otherwise use the authenticated user (may be None for scripts).
        final_requested_by = requested_by or user

        try:
            reservation = Reservation.objects.create(
                facility=facility,
                coach=coach,
                requested_by=final_requested_by,
                **validated_data,
            )
        except DjangoValidationError as e:
            # Translate Django ValidationError into serializer-friendly format
            err = self._translate_model_validation_error(e)
            raise serializers.ValidationError(err)

        return reservation

    def update(self, instance, validated_data):
        request = self.context.get("request")
        user = request.user if request else None

        # Allow admin to change status (approve/reject)
        new_status = validated_data.get("status")
        if new_status and new_status != instance.status:
            # only admins should approve/reject
            if not user or not user.is_admin:
                raise serializers.ValidationError(
                    "Only admins can change reservation status."
                )
            instance.status = new_status

        # Allow updating times/notes by requester or admin
        if "start_datetime" in validated_data:
            instance.start_datetime = validated_data["start_datetime"]
        if "end_datetime" in validated_data:
            instance.end_datetime = validated_data["end_datetime"]
        if "notes" in validated_data:
            instance.notes = validated_data["notes"]

        try:
            instance.save()
        except DjangoValidationError as e:
            err = self._translate_model_validation_error(e)
            raise serializers.ValidationError(err)

        return instance

    def _translate_model_validation_error(self, error: DjangoValidationError):
        """Convert Django ValidationError into a dict of serializer field errors.

        Maps model field names to frontend form field keys where helpful.
        """
        # Default mapping from model fields -> API/serializer keys -> frontend form keys
        field_map = {
            "start_datetime": "start_datetime",
            "end_datetime": "end_datetime",
            "facility": "facility_id",
            "notes": "notes",
        }

        # Also include frontend-specific form keys (used by client-side zod schema)
        frontend_map = {
            "start_datetime": "startDate",
            "end_datetime": "endDate",
            "facility": "facility_id",
            "notes": "description",
        }

        # If error has a message_dict, convert it; otherwise use messages
        errors = {}
        if hasattr(error, "message_dict") and error.message_dict:
            for field, messages in error.message_dict.items():
                key = field_map.get(field, field)
                errors.setdefault(key, []).extend(messages)
                # also add frontend key if different
                frontend_key = frontend_map.get(field)
                if frontend_key and frontend_key != key:
                    errors.setdefault(frontend_key, []).extend(messages)
        else:
            # Non-field errors or single message
            messages = error.messages if hasattr(error, "messages") else [str(error)]
            errors[serializers.api_settings.NON_FIELD_ERRORS_KEY] = messages

        return errors
