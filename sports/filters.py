import django_filters
from django.db.models import Q
from .models import Position, SportStatType, Formula


class SportStatTypeFilter(django_filters.FilterSet):
    sport = django_filters.CharFilter(field_name="sport__slug", lookup_expr="iexact")
    is_record = django_filters.BooleanFilter()
    search = django_filters.CharFilter(method="filter_search")
    category = django_filters.CharFilter(method="filter_category")
    type = django_filters.CharFilter(method="filter_type")

    class Meta:
        model = SportStatType
        fields = ["sport", "is_record", "search", "category", "type"]

    def filter_search(self, queryset, name, value):
        if value:
            return queryset.filter(
                Q(name__icontains=value) |
                Q(code__icontains=value) |
                Q(display_name__icontains=value)
            )
        return queryset

    def filter_category(self, queryset, name, value):
        if value == "all":
            return queryset
        # Use the actual category field from the model
        return queryset.filter(category=value)

    def filter_type(self, queryset, name, value):
        if value == "all":
            return queryset
        elif value == "basic":
            return queryset.filter(is_record=True)
        elif value == "advanced":
            return queryset.filter(is_record=False)
        return queryset


class SportPositionFilter(django_filters.FilterSet):
    sport = django_filters.CharFilter(field_name="sport__slug", lookup_expr="iexact")

    class Meta:
        model = Position
        fields = ["sport"]
