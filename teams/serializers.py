from rest_framework.serializers import ModelSerializer, Serializer
from rest_framework import serializers
from django.db import models, IntegrityError
from .models import Team, Player, Coach, AcademicInfo, PlayerRegistration, PlayerRegistrationDocument
from users.serializers import PlayerSerializer, CoachSerializer
from users.models import User
from sports.models import Sport, Position
from sports.serializers import SportSerializer, PositionSerializer

# Import Game model for the summary serializer
from games.models import Game


class AcademicInfoSerializer(ModelSerializer):
    """Serializer for AcademicInfo model"""
    
    class Meta:
        model = AcademicInfo
        fields = ['id', 'year_level', 'course', 'section']


class GameSummarySerializer(ModelSerializer):
    """Simplified game serializer for analytics and performance data"""

    home_team_name = serializers.CharField(source="home_team.name", read_only=True)
    away_team_name = serializers.CharField(source="away_team.name", read_only=True)
    home_team_abbreviation = serializers.CharField(
        source="home_team.abbreviation", read_only=True
    )
    away_team_abbreviation = serializers.CharField(
        source="away_team.abbreviation", read_only=True
    )
    result = serializers.SerializerMethodField()
    score_summary = serializers.SerializerMethodField()

    class Meta:
        model = Game
        fields = [
            "id",
            "date",
            "time",
            "home_team_name",
            "away_team_name",
            "home_team_abbreviation",
            "away_team_abbreviation",
            "home_team_score",
            "away_team_score",
            "status",
            "result",
            "score_summary",
            "location",
        ]

    def get_result(self, obj):
        """Determine the result from the perspective of the requesting team"""
        # Get the team from context if available
        request = self.context.get("request")
        team = self.context.get("team")

        if not team or obj.status != Game.Status.COMPLETED:
            return None

        if obj.winner_team == team:
            return "win"
        elif obj.winner_team is None:
            return "draw"
        else:
            return "loss"

    def get_score_summary(self, obj):
        """Get a formatted score summary"""
        if obj.home_team_score is not None and obj.away_team_score is not None:
            return f"{obj.home_team_score} - {obj.away_team_score}"
        return "TBD"


class SimpleTeamSerializer(ModelSerializer):
    """Simplified team serializer to avoid circular imports when used in coach info"""

    logo = serializers.ImageField(use_url=True, required=False)
    sport_name = serializers.CharField(source="sport.name", read_only=True)
    player_count = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = [
            "id",
            "name",
            "abbreviation",
            "color",
            "logo",
            "sport_name",
            "division",
            "slug",
            "player_count",
            "is_active",
        ]

    def get_player_count(self, obj):
        return obj.players.count()


class TeamSerializer(ModelSerializer):
    logo = serializers.ImageField(use_url=True, required=False)
    head_coach_name = serializers.SerializerMethodField()
    assistant_coach_name = serializers.SerializerMethodField()
    head_coach_id = serializers.IntegerField(
        source="head_coach.user.id", read_only=True, allow_null=True
    )
    assistant_coach_id = serializers.IntegerField(
        source="assistant_coach.user.id", read_only=True, allow_null=True
    )
    sport_name = serializers.CharField(source="sport.name", read_only=True)
    player_count = serializers.SerializerMethodField()
    can_be_hard_deleted = serializers.SerializerMethodField()
    has_associated_data = serializers.SerializerMethodField()

    # Enhanced coach information
    head_coach_info = serializers.SerializerMethodField()
    assistant_coach_info = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = "__all__"
        read_only_fields = ("created_at", "slug")

    def get_head_coach_name(self, obj):
        if obj.head_coach and obj.head_coach.user:
            return f"{obj.head_coach.user.first_name} {obj.head_coach.user.last_name}"
        return None

    def get_assistant_coach_name(self, obj):
        if obj.assistant_coach and obj.assistant_coach.user:
            return f"{obj.assistant_coach.user.first_name} {obj.assistant_coach.user.last_name}"
        return None

    def get_player_count(self, obj):
        return obj.players.count()

    def get_can_be_hard_deleted(self, obj):
        """Check if team can be safely hard deleted"""
        return obj.can_be_hard_deleted()

    def get_has_associated_data(self, obj):
        """Check if team has associated games or training sessions"""
        return obj.has_associated_data()

    def get_head_coach_info(self, obj):
        """Return comprehensive head coach information"""
        if not obj.head_coach:
            return None

        coach = obj.head_coach
        user = coach.user

        return {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": f"{user.first_name} {user.last_name}",
            "email": user.email,
            "sex": user.sex,
            "profile": user.profile.url if user.profile else None,
            "sports": [
                {"id": sport.id, "name": sport.name, "slug": sport.slug}
                for sport in coach.sports.all()
            ],
            "head_coached_teams_count": coach.head_coached_teams.count(),
            "assistant_coached_teams_count": coach.assistant_coached_teams.count(),
        }

    def get_assistant_coach_info(self, obj):
        """Return comprehensive assistant coach information"""
        if not obj.assistant_coach:
            return None

        coach = obj.assistant_coach
        user = coach.user

        return {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": f"{user.first_name} {user.last_name}",
            "email": user.email,
            "sex": user.sex,
            "profile": user.profile.url if user.profile else None,
            "sports": [
                {"id": sport.id, "name": sport.name, "slug": sport.slug}
                for sport in coach.sports.all()
            ],
            "head_coached_teams_count": coach.head_coached_teams.count(),
            "assistant_coached_teams_count": coach.assistant_coached_teams.count(),
        }

    def validate(self, data):
        """Validate that coaches can handle the sport for this team and team name is unique"""
        head_coach = data.get("head_coach")
        assistant_coach = data.get("assistant_coach")
        sport = data.get("sport")
        name = data.get("name")
        division = data.get("division")

        # If we're updating, get current values if not provided
        if self.instance:
            head_coach = head_coach or self.instance.head_coach
            assistant_coach = assistant_coach or self.instance.assistant_coach
            sport = sport or self.instance.sport
            name = name or self.instance.name
            division = division or self.instance.division

        # Validate unique team name within sport and division
        if name and sport and division:
            existing_team = Team.objects.filter(
                name__iexact=name, sport=sport, division=division
            )
            if self.instance:
                existing_team = existing_team.exclude(pk=self.instance.pk)

            if existing_team.exists():
                raise serializers.ValidationError(
                    {
                        "name": f"A team with the name '{name}' already exists in {sport.name} {division} division."
                    }
                )

        # Validate coaches can handle the sport
        if (
            head_coach
            and sport
            and not head_coach.can_coach_team(type("Team", (), {"sport": sport})())
        ):
            raise serializers.ValidationError(
                {
                    "head_coach": f"Selected head coach cannot coach {sport.name} teams. Please assign a coach who handles this sport."
                }
            )

        if (
            assistant_coach
            and sport
            and not assistant_coach.can_coach_team(type("Team", (), {"sport": sport})())
        ):
            raise serializers.ValidationError(
                {
                    "assistant_coach": f"Selected assistant coach cannot coach {sport.name} teams. Please assign a coach who handles this sport."
                }
            )

        return data

    def create(self, validated_data):
        """Create a new team instance with proper validation"""
        try:
            instance = Team(**validated_data)
            instance.full_clean()  # This calls the model's clean() method
            instance.save()
            return instance
        except Exception as e:
            # Convert any remaining integrity errors to validation errors
            if "slug" in str(e) and "unique constraint" in str(e):
                raise serializers.ValidationError(
                    {
                        "name": "Team name conflicts with existing team. Please choose a different name."
                    }
                )
            raise e


class SportsTeamSerializer(Serializer):
    sport = serializers.CharField()
    teams = TeamSerializer(many=True, read_only=True)


class PlayerInfoSerializer(ModelSerializer):
    id = serializers.IntegerField(source="user.id", read_only=True)
    profile = serializers.ImageField(source="user.profile", required=False)
    first_name = serializers.CharField(source="user.first_name", required=True)
    last_name = serializers.CharField(source="user.last_name", required=True)
    sex = serializers.CharField(source="user.sex", required=True)
    slug = serializers.CharField(read_only=True)
    email = serializers.EmailField(source="user.email", required=True)

    team_id = serializers.PrimaryKeyRelatedField(
        queryset=Team.objects.all(), write_only=True, required=False, allow_null=True
    )
    position_ids = serializers.PrimaryKeyRelatedField(
        queryset=Position.objects.all(), many=True, write_only=True, required=False
    )
    sport_slug = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=Sport.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    
    # AcademicInfo fields
    academic_info_id = serializers.PrimaryKeyRelatedField(
        queryset=AcademicInfo.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
        source='academic_info'
    )
    academic_info = AcademicInfoSerializer(read_only=True)

    # Read-only nested serializers
    team = TeamSerializer(read_only=True)
    positions = PositionSerializer(many=True, read_only=True, source="position")
    sport = SportSerializer(read_only=True)

    full_name = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(source="user.is_active", read_only=True)
    can_be_hard_deleted = serializers.SerializerMethodField()
    has_associated_data = serializers.SerializerMethodField()

    class Meta:
        model = Player
        fields = [
            "id",
            "profile",
            "first_name",
            "last_name",
            "full_name",
            "sex",
            "email",
            "slug",
            "academic_info_id",
            "academic_info",
            "height",
            "weight",
            "team_id",
            "team",
            "jersey_number",
            "position_ids",
            "positions",
            "sport_slug",
            "sport",
            "is_active",
            "can_be_hard_deleted",
            "has_associated_data",
        ]

    def validate_position_ids(self, value):
        # Get the sport from the validated data to check if it requires stats
        sport_slug = self.initial_data.get("sport_slug")
        if sport_slug:
            try:
                sport = Sport.objects.get(slug=sport_slug)
                # Only require positions for sports that require stats
                if sport.requires_stats and not value:
                    raise serializers.ValidationError(
                        "At least one position is required for this sport."
                    )
            except Sport.DoesNotExist:
                pass
        elif not value:
            # Default behavior if sport not found - require positions
            raise serializers.ValidationError("At least one position is required.")
        return value

    def validate(self, data):
        """Validate team capacity and other constraints"""
        team = data.get("team_id")
        sport = data.get("sport_slug")

        # If we're updating, get current values if not provided
        if self.instance:
            team = team or self.instance.team
            sport = sport or self.instance.sport

        # Validate team capacity
        if team and sport:
            # Check if adding this player would exceed the team's maximum capacity
            current_player_count = team.players.count()

            # If we're updating, don't count the current player
            if self.instance:
                current_player_count -= 1

            if current_player_count >= sport.max_players_per_team:
                raise serializers.ValidationError(
                    {
                        "team_id": f"Team '{team.name}' has reached its maximum capacity of {sport.max_players_per_team} players for {sport.name}."
                    }
                )

        # Validate jersey number uniqueness within the team
        jersey_number = data.get("jersey_number")
        if team and jersey_number:
            existing_player = Player.objects.filter(
                team=team, jersey_number=jersey_number
            )

            # If updating, exclude current player
            if self.instance:
                existing_player = existing_player.exclude(pk=self.instance.pk)

            if existing_player.exists():
                raise serializers.ValidationError(
                    {
                        "jersey_number": f"Jersey number {jersey_number} is already taken by another player in team '{team.name}'."
                    }
                )

        return data

    def to_internal_value(self, data):
        """
        Override to properly group user fields together
        """
        internal_value = super().to_internal_value(data)

        # Extract user-related fields and group them
        user_fields = ["profile", "first_name", "last_name", "sex", "email"]
        user_data = {}

        for field in user_fields:
            if field in internal_value:
                user_data[field] = internal_value.pop(field)

        if user_data:
            internal_value["user"] = user_data

        return internal_value

    def create(self, validated_data):
        from django.db import transaction

        user_data = validated_data.pop("user", {})
        team = validated_data.pop("team_id", None)
        positions = validated_data.pop("position_ids", [])
        sport = validated_data.pop("sport_slug", None)

        # Use atomic transaction to ensure both user and player are created together
        # If player creation fails, user creation will be rolled back
        with transaction.atomic():
            user_serializer = PlayerSerializer(data=user_data)
            user_serializer.is_valid(raise_exception=True)
            user = user_serializer.save()

            player = Player.objects.create(
                user=user, team=team, sport=sport, **validated_data
            )
            player.position.set(positions)
            return player

    def update(self, instance, validated_data):
        from django.db import transaction

        user_data = validated_data.pop("user", {})
        team = validated_data.pop("team_id", None)
        positions = validated_data.pop("position_ids", None)
        sport = validated_data.pop("sport_slug", None)

        # Use atomic transaction to ensure both user and player updates succeed together
        with transaction.atomic():
            if user_data:
                user_serializer = PlayerSerializer(
                    instance.user, data=user_data, partial=True
                )
                user_serializer.is_valid(raise_exception=True)
                user_serializer.save()

            if team is not None:
                instance.team = team
            if sport is not None:
                instance.sport = sport
            if positions is not None:
                instance.position.set(positions)

            # Only update the player model with remaining player data (not user data)
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            return instance

    def get_full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"

    def get_can_be_hard_deleted(self, obj):
        """Check if player can be safely hard deleted"""
        return obj.can_be_hard_deleted()

    def get_has_associated_data(self, obj):
        """Check if player has associated data"""
        return obj.has_associated_data()


class CoachInfoSerializer(ModelSerializer):
    id = serializers.IntegerField(source="user.id", read_only=True)
    profile = serializers.ImageField(source="user.profile", required=False)
    first_name = serializers.CharField(source="user.first_name", required=True)
    last_name = serializers.CharField(source="user.last_name", required=True)
    email = serializers.EmailField(source="user.email", required=True)
    sex = serializers.CharField(source="user.sex", required=True)
    # Combined teams field
    coached_teams = serializers.SerializerMethodField()
    # Sports handling
    sport_ids = serializers.PrimaryKeyRelatedField(
        queryset=Sport.objects.all(),
        many=True,
        write_only=True,
        required=False,
        source="sports",
    )
    sports = SportSerializer(many=True, read_only=True)
    full_name = serializers.SerializerMethodField()
    team_count = serializers.SerializerMethodField()
    player_count = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(source="user.is_active", read_only=True)
    can_be_hard_deleted = serializers.SerializerMethodField()
    has_associated_data = serializers.SerializerMethodField()

    class Meta:
        model = Coach
        fields = [
            "id",
            "profile",
            "first_name",
            "last_name",
            "full_name",
            "sex",
            "email",
            "coached_teams",
            "sport_ids",
            "sports",
            "team_count",
            "player_count",
            "is_active",
            "can_be_hard_deleted",
            "has_associated_data",
        ]

    def get_full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"

    def get_coached_teams(self, obj):
        # Get unique teams where coach is head or assistant
        head_teams = obj.head_coached_teams.all()
        assistant_teams = obj.assistant_coached_teams.all()
        all_teams = {team.id: team for team in list(head_teams) + list(assistant_teams)}
        return SimpleTeamSerializer(
            all_teams.values(), many=True, context=self.context
        ).data

    def get_team_count(self, obj):
        head_team_ids = set(obj.head_coached_teams.values_list("id", flat=True))
        assistant_team_ids = set(
            obj.assistant_coached_teams.values_list("id", flat=True)
        )
        return len(head_team_ids.union(assistant_team_ids))

    def get_player_count(self, obj):
        team_ids = set(obj.head_coached_teams.values_list("id", flat=True)).union(
            obj.assistant_coached_teams.values_list("id", flat=True)
        )
        from .models import Team

        players = set()
        for team in Team.objects.filter(id__in=team_ids):
            players.update(team.players.values_list("user_id", flat=True))
        return len(players)

    def get_can_be_hard_deleted(self, obj):
        """Check if coach can be safely hard deleted"""
        return obj.can_be_hard_deleted()

    def get_has_associated_data(self, obj):
        """Check if coach has associated data"""
        return obj.has_associated_data()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def create(self, validated_data):
        from django.db import transaction

        user_data = validated_data.pop("user")
        sports = validated_data.pop("sports", [])

        # Use atomic transaction to ensure both user and coach are created together
        with transaction.atomic():
            # Create the User instance using the nested serializer
            user_serializer = CoachSerializer(data=user_data)
            user_serializer.is_valid(raise_exception=True)  # Ensures data is valid
            user = user_serializer.save()

            # Create the Coach instance with the user instance
            coach = Coach.objects.create(user=user, **validated_data)
            coach.sports.set(sports)
            return coach

    def update(self, instance, validated_data):
        from django.db import transaction

        user_data = validated_data.pop("user", {})
        sports = validated_data.pop("sports", None)
        user = instance.user

        # Use atomic transaction to ensure both user and coach updates succeed together
        with transaction.atomic():
            # Validate email uniqueness if provided to give friendly error
            new_email = user_data.get("email")
            if new_email:
                # If email is changing and it's already used by another user, raise validation error
                if User.objects.exclude(pk=user.pk).filter(email=new_email).exists():
                    raise serializers.ValidationError({"email": "This email is already in use."})

            # Update the User model
            for attr, value in user_data.items():
                setattr(user, attr, value)

            try:
                user.save()
            except IntegrityError as e:
                # Translate DB integrity errors (unique constraint) into ValidationError
                # Common case: duplicate email
                if 'email' in str(e).lower():
                    raise serializers.ValidationError({"email": "This email is already in use."})
                raise serializers.ValidationError({"detail": "Failed to update user: integrity error."})

            # Update sports if provided
            if sports is not None:
                instance.sports.set(sports)

            # Update the Coach model
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            return instance


# ============== Player Registration Serializers ==============

class PlayerRegistrationDocumentSerializer(ModelSerializer):
    """Serializer for registration documents with Cloudinary URLs"""
    document_type_display = serializers.CharField(source='get_document_type_display', read_only=True)
    file_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    
    class Meta:
        model = PlayerRegistrationDocument
        fields = [
            'id', 'document_type', 'document_type_display', 'title', 
            'file', 'file_url', 'preview_url', 'download_url',
            'file_extension', 'uploaded_at', 'synced_document'
        ]
        read_only_fields = ['uploaded_at', 'file_extension', 'synced_document']
    
    def get_file_url(self, obj):
        """Get the Cloudinary file URL"""
        return obj.file_url
    
    def get_preview_url(self, obj):
        """Get the Microsoft Office Online preview URL"""
        return obj.preview_url
    
    def get_download_url(self, obj):
        """Get the download URL"""
        return obj.download_url


class PlayerRegistrationDocumentUploadSerializer(ModelSerializer):
    """Serializer for uploading registration documents"""
    
    class Meta:
        model = PlayerRegistrationDocument
        fields = ['document_type', 'title', 'file']
    
    def validate_file(self, value):
        # Validate file size (max 10MB)
        max_size = 10 * 1024 * 1024  # 10MB
        if value.size > max_size:
            raise serializers.ValidationError("File size cannot exceed 10MB.")
        
        # Validate file extension
        import os
        _, ext = os.path.splitext(value.name)
        allowed_extensions = ['.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png']
        if ext.lower() not in allowed_extensions:
            raise serializers.ValidationError(
                f"File type not allowed. Allowed types: {', '.join(allowed_extensions)}"
            )
        
        return value


class PlayerRegistrationListSerializer(ModelSerializer):
    """Serializer for listing player registrations"""
    sport = SportSerializer(read_only=True)
    team = SimpleTeamSerializer(read_only=True)
    positions = PositionSerializer(many=True, read_only=True, source='position')
    academic_info = AcademicInfoSerializer(read_only=True)
    documents_count = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    
    class Meta:
        model = PlayerRegistration
        fields = [
            'id', 'email', 'first_name', 'last_name', 'full_name', 'sex',
            'date_of_birth', 'phone_number', 'height', 'weight',
            'sport', 'positions', 'academic_info', 'team', 'jersey_number',
            'status', 'documents_count', 'created_at', 'updated_at',
            'reviewed_by_name', 'reviewed_at', 'rejection_reason'
        ]
    
    def get_documents_count(self, obj):
        return obj.documents.count()
    
    def get_full_name(self, obj):
        return obj.get_full_name()
    
    def get_reviewed_by_name(self, obj):
        if obj.reviewed_by:
            return obj.reviewed_by.get_full_name()
        return None


class PlayerRegistrationDetailSerializer(ModelSerializer):
    """Serializer for detailed player registration view"""
    sport = SportSerializer(read_only=True)
    team = SimpleTeamSerializer(read_only=True)
    positions = PositionSerializer(many=True, read_only=True, source='position')
    academic_info = AcademicInfoSerializer(read_only=True)
    documents = PlayerRegistrationDocumentSerializer(many=True, read_only=True)
    full_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    approved_player_info = serializers.SerializerMethodField()
    
    class Meta:
        model = PlayerRegistration
        fields = [
            'id', 'email', 'first_name', 'last_name', 'full_name', 'sex',
            'date_of_birth', 'phone_number', 'height', 'weight',
            'sport', 'positions', 'academic_info', 'team', 'jersey_number',
            'status', 'documents', 'created_at', 'updated_at',
            'reviewed_by', 'reviewed_by_name', 'reviewed_at', 'rejection_reason',
            'approved_player', 'approved_player_info'
        ]
    
    def get_full_name(self, obj):
        return obj.get_full_name()
    
    def get_reviewed_by_name(self, obj):
        if obj.reviewed_by:
            return obj.reviewed_by.get_full_name()
        return None
    
    def get_approved_player_info(self, obj):
        if obj.approved_player:
            return {
                'id': obj.approved_player.user.id,
                'slug': obj.approved_player.slug,
                'full_name': obj.approved_player.user.get_full_name(),
            }
        return None


class PlayerRegistrationCreateSerializer(ModelSerializer):
    """Serializer for creating a player registration (self-registration)"""
    sport_id = serializers.PrimaryKeyRelatedField(
        queryset=Sport.objects.all(),
        source='sport',
        write_only=True
    )
    position_ids = serializers.PrimaryKeyRelatedField(
        queryset=Position.objects.all(),
        many=True,
        required=False,
        write_only=True
    )
    academic_info_id = serializers.PrimaryKeyRelatedField(
        queryset=AcademicInfo.objects.all(),
        source='academic_info',
        required=False,
        allow_null=True,
        write_only=True
    )
    documents = PlayerRegistrationDocumentUploadSerializer(many=True, required=False, write_only=True)
    
    # Read-only fields for response
    sport = SportSerializer(read_only=True)
    positions = PositionSerializer(many=True, read_only=True, source='position')
    academic_info = AcademicInfoSerializer(read_only=True)
    
    class Meta:
        model = PlayerRegistration
        fields = [
            'id', 'email', 'first_name', 'last_name', 'sex',
            'date_of_birth', 'phone_number', 'height', 'weight',
            'sport_id', 'sport', 'position_ids', 'positions',
            'academic_info_id', 'academic_info',
            'documents', 'status', 'created_at'
        ]
        read_only_fields = ['status', 'created_at']
    
    def validate_email(self, value):
        # Check if email already exists in User model
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        
        # Check if there's already a pending registration with this email
        if PlayerRegistration.objects.filter(email=value, status=PlayerRegistration.Status.PENDING).exists():
            raise serializers.ValidationError("A pending registration with this email already exists.")
        
        return value
    
    def validate_position_ids(self, value):
        sport_id = self.initial_data.get('sport_id')
        if sport_id:
            try:
                sport = Sport.objects.get(pk=sport_id)
                if sport.requires_stats and not value:
                    raise serializers.ValidationError(
                        "At least one position is required for this sport."
                    )
            except Sport.DoesNotExist:
                pass
        return value
    
    def validate(self, attrs):
        # Validate positions belong to the selected sport
        positions = attrs.get('position_ids', [])
        sport = attrs.get('sport')
        
        if positions and sport:
            for position in positions:
                if position.sport != sport:
                    raise serializers.ValidationError({
                        'position_ids': f"Position '{position.name}' does not belong to sport '{sport.name}'."
                    })
        
        return attrs
    
    def create(self, validated_data):
        from django.db import transaction
        
        positions = validated_data.pop('position_ids', [])
        documents_data = validated_data.pop('documents', [])
        
        with transaction.atomic():
            registration = PlayerRegistration.objects.create(**validated_data)
            
            if positions:
                registration.position.set(positions)
            
            # Create documents
            for doc_data in documents_data:
                PlayerRegistrationDocument.objects.create(
                    registration=registration,
                    **doc_data
                )
            
            return registration


class PlayerRegistrationApproveSerializer(serializers.Serializer):
    """Serializer for approving a player registration"""
    team_id = serializers.PrimaryKeyRelatedField(
        queryset=Team.objects.all(),
        required=True
    )
    jersey_number = serializers.IntegerField(required=True, min_value=0, max_value=99)
    
    def validate(self, attrs):
        team = attrs.get('team_id')
        jersey_number = attrs.get('jersey_number')
        
        # Validate jersey number uniqueness within team
        if Player.objects.filter(team=team, jersey_number=jersey_number).exists():
            raise serializers.ValidationError({
                'jersey_number': f"Jersey number {jersey_number} is already taken in team '{team.name}'."
            })
        
        # Validate team capacity
        registration = self.context.get('registration')
        if registration and team:
            sport = registration.sport
            current_player_count = team.players.count()
            if current_player_count >= sport.max_players_per_team:
                raise serializers.ValidationError({
                    'team_id': f"Team '{team.name}' has reached its maximum capacity of {sport.max_players_per_team} players."
                })
        
        return attrs


class PlayerRegistrationRejectSerializer(serializers.Serializer):
    """Serializer for rejecting a player registration"""
    rejection_reason = serializers.CharField(required=True, max_length=1000)


class PlayerDocumentUploadSerializer(serializers.Serializer):
    """Serializer for uploading documents to an existing player (coach-created)"""
    
    class DocumentType(models.TextChoices):
        MEDICAL_CERT = "medical_cert", "Medical Certificate"
        PARENT_CONSENT = "parent_consent", "Parent/Guardian Consent Form"
        ID_DOCUMENT = "id_document", "ID Document"
        OTHER = "other", "Other"
    
    document_type = serializers.ChoiceField(choices=DocumentType.choices, required=True)
    title = serializers.CharField(max_length=255, required=True)
    file = serializers.FileField(required=True)
    
    def validate_file(self, value):
        # Validate file size (max 10MB)
        max_size = 10 * 1024 * 1024  # 10MB
        if value.size > max_size:
            raise serializers.ValidationError("File size cannot exceed 10MB.")
        
        # Validate file extension
        import os
        _, ext = os.path.splitext(value.name)
        allowed_extensions = ['.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png']
        if ext.lower() not in allowed_extensions:
            raise serializers.ValidationError(
                f"File type not allowed. Allowed types: {', '.join(allowed_extensions)}"
            )
        
        return value
