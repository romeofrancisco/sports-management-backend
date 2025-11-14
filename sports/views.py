from rest_framework.viewsets import ModelViewSet
from .models import Sport, Position, SportStatCategory, SportStatType, Formula, LeaderCategory
from .serializers import (
    SportSerializer,
    PositionSerializer,
    SportStatCategorySerializer,
    SportStatTypeSerializer,
    FormulaSerializer,
    LeaderCategorySerializer,
)
from sports_management.permissions import IsAdminUser
from django_filters.rest_framework import DjangoFilterBackend
from .filters import SportStatTypeFilter, SportPositionFilter
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from rest_framework.filters import SearchFilter
from rest_framework import viewsets, status
from rest_framework.decorators import action
from django.db.models import Count
from rest_framework.permissions import IsAuthenticated, SAFE_METHODS
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError


class SportsViewSet(ModelViewSet):
    queryset = Sport.objects.all()  # Show all sports (active and inactive) for admin
    serializer_class = SportSerializer
    lookup_field = "slug"
    
    def get_permissions(self):
        """
        Custom permissions:
        - GET requests can be made by any authenticated user
        - POST/PUT/DELETE requests require admin permissions
        """
        if self.request.method in SAFE_METHODS:  # GET, HEAD, OPTIONS
            return [IsAuthenticated()]  # Any authenticated user can read
        return [IsAdminUser()]  # Admin permission required for write operations

    def get_queryset(self):
        """
        Filter queryset based on user role and query parameters
        """
        queryset = super().get_queryset()
        
        # Add filter for showing only active sports if requested
        show_inactive = self.request.query_params.get('show_inactive', 'false').lower() == 'true'
        
        if not show_inactive and self.action == 'list':
            # For regular list view, only show active sports unless explicitly requested
            if not self.request.user.is_admin:
                queryset = queryset.filter(is_active=True)
        
        return queryset
    

    def destroy(self, request, *args, **kwargs):
        """
        Custom destroy method that handles soft delete for sports with associated data
        """
        sport = self.get_object()
        
        if sport.has_associated_data():
            # Soft delete - deactivate the sport
            sport.soft_delete()
            return Response({
                'message': 'Sport has been deactivated due to associated games/teams/data',
                'status': 'deactivated',
                'sport_name': sport.name
            }, status=status.HTTP_200_OK)
        else:
            # Hard delete is safe - no associated data
            sport_name = sport.name
            sport.delete()
            return Response({
                'message': f'Sport "{sport_name}" has been permanently deleted',
                'status': 'deleted',
                'sport_name': sport_name
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def reactivate(self, request, slug=None):
        """
        Reactivate a deactivated sport
        """
        sport = self.get_object()
        
        if sport.is_active:
            return Response({
                'message': f'Sport "{sport.name}" is already active',
                'status': 'already_active',
                'sport_name': sport.name
            }, status=status.HTTP_200_OK)
        
        sport.reactivate()
        return Response({
            'message': f'Sport "{sport.name}" has been reactivated successfully',
            'status': 'reactivated',
            'sport_name': sport.name
        }, status=status.HTTP_200_OK)

class SportStatCategoryViewSet(ModelViewSet):
    queryset = SportStatCategory.objects.all()
    serializer_class = SportStatCategorySerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        sport = self.request.query_params.get("sport")
        
        if sport:
            sport = get_object_or_404(Sport, slug=sport)
            queryset = queryset.filter(sport=sport)
            
        return queryset

class SportStatTypeViewSet(ModelViewSet):
    queryset = SportStatType.objects.select_related("sport").all()
    serializer_class = SportStatTypeSerializer
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ["name"]
    filterset_class = SportStatTypeFilter
    
    def get_queryset(self):
        queryset = super().get_queryset()
        sport_slug = self.request.query_params.get("sport")
        
        if sport_slug:
            sport = get_object_or_404(Sport, slug=sport_slug)
            queryset = queryset.filter(sport=sport)
            
        return queryset
    
    @action(detail=False, methods=['get'])
    def overview(self, request):
        """Get overview statistics for sport stat types"""
        sport_slug = request.query_params.get('sport')
        
        if not sport_slug:
            return Response({"error": "Sport slug is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        sport = get_object_or_404(Sport, slug=sport_slug)
        queryset = self.queryset.filter(sport=sport)
        
        # Calculate overview statistics
        total_stats = queryset.count()
        recording_stats = queryset.filter(is_record=True).count()
        calculated_stats = queryset.filter(is_record=False).count()
        boxscore_stats = queryset.filter(is_boxscore=True).count()
        team_comparison_stats = queryset.filter(is_team_comparison=True).count()
        
        # Category breakdown
        scoring_stats = queryset.filter(point_value__gt=0).count()
        performance_stats = queryset.filter(name__icontains='%').count()
        negative_stats = queryset.filter(is_negative=True).count()
        
        # Additional insights
        stats_with_formulas = queryset.filter(formula__isnull=False).count()
        stats_with_point_values = queryset.exclude(point_value=0).count()
        
        overview_data = {
            'total_stats': total_stats,
            'stat_types': {
                'recording': recording_stats,
                'calculated': calculated_stats,
                'boxscore': boxscore_stats,
                'team_comparison': team_comparison_stats,
            },
            'categories': {
                'scoring': scoring_stats,
                'performance': performance_stats,
                'negative': negative_stats,
                'other': total_stats - (scoring_stats + performance_stats + negative_stats)
            },
            'features': {
                'with_formulas': stats_with_formulas,
                'with_point_values': stats_with_point_values,
                'without_point_values': total_stats - stats_with_point_values
            },
            'sport': {
                'name': sport.name,
                'slug': sport.slug
            }
        }
        
        return Response(overview_data)


class FormulaViewSet(ModelViewSet):
    queryset = Formula.objects.all().prefetch_related(
        "components", "components__stat_type", "sport"
    )
    serializer_class = FormulaSerializer
    filter_backends = [SearchFilter]
    permission_classes = [IsAdminUser]
    search_fields = ["name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        sport_slug = self.request.query_params.get("sport")

        if sport_slug:
            sport = get_object_or_404(Sport, slug=sport_slug)
            queryset = queryset.filter(sport=sport)

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=201, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)


class PositionViewSet(ModelViewSet):
    serializer_class = PositionSerializer
    queryset = Position.objects.select_related("sport").all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = SportPositionFilter
    
    def get_permissions(self):
        """
        Custom permissions:
        - GET requests can be made by any authenticated user
        - POST/PUT/DELETE requests require admin permissions
        """
        if self.request.method in SAFE_METHODS:  # GET, HEAD, OPTIONS
            return [IsAuthenticated()]  # Any authenticated user can read
        return [IsAdminUser()]  # Admin permission required for write operations

    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            raise ValidationError({
                "detail": "A position with the same name or abbreviation already exists for this sport."
            })

    def perform_update(self, serializer):
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            raise ValidationError({
                "detail": "A position with the same name or abbreviation already exists for this sport."
            })

class LeaderCategoryViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing game and season leader categories.
    """
    queryset = LeaderCategory.objects.all()
    serializer_class = LeaderCategorySerializer
    
    def get_permissions(self):
        """
        Custom permissions:
        - GET requests can be made by any authenticated user
        - POST/PUT/DELETE requests require admin permissions
        """
        if self.request.method in SAFE_METHODS:  # GET, HEAD, OPTIONS
            return [IsAuthenticated()]  # Any authenticated user can read
        return [IsAdminUser()]  # Admin permission required for write operations
    
    def get_queryset(self):
        queryset = super().get_queryset()
        sport_slug = self.request.query_params.get('sport')
        leader_type = self.request.query_params.get('leader_type')
        
        if sport_slug:
            queryset = queryset.filter(sport__slug=sport_slug)
        
        if leader_type:
            if leader_type == 'game':
                queryset = queryset.filter(leader_type__in=['game', 'both'])
            elif leader_type == 'season':
                queryset = queryset.filter(leader_type__in=['season', 'both'])
                
        return queryset.select_related('sport').prefetch_related('stat_types')
    
    @action(detail=False, methods=['get'])
    def by_sport(self, request):
        """Get leader categories grouped by sport"""
        sport_slug = request.query_params.get('sport')
        leader_type = request.query_params.get('leader_type', 'both')
        
        if not sport_slug:
            return Response({"error": "Sport slug is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        sport = get_object_or_404(Sport, slug=sport_slug)
        
        if leader_type == 'game':
            queryset = self.queryset.filter(
                sport=sport, 
                leader_type__in=['game', 'both']
            )
        elif leader_type == 'season':
            queryset = self.queryset.filter(
                sport=sport, 
                leader_type__in=['season', 'both']
            )
        else:
            queryset = self.queryset.filter(sport=sport)
            
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
