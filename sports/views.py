from rest_framework.viewsets import ModelViewSet
from .models import Sport, Position, SportStatType, Formula, LeaderCategory
from .serializers import (
    SportSerializer,
    PositionSerializer,
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


class SportsViewSet(ModelViewSet):
    queryset = Sport.objects.all()
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


class SportStatTypeViewSet(ModelViewSet):
    queryset = SportStatType.objects.select_related("sport").all()
    serializer_class = SportStatTypeSerializer
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ["name"]
    filterset_class = SportStatTypeFilter


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
