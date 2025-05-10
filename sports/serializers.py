from rest_framework import serializers
from .models import Sport, Position, SportStatType, Formula, FormulaComponent, LeaderCategory
from games.models import PlayerStat
from django.db.models import Count

class SportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sport
        fields = "__all__"
        read_only_fields = ("created_at", "slug")

class FormulaComponentSerializer(serializers.ModelSerializer):
    stat_type_id = serializers.CharField(source='stat_type.id', read_only=True)
    stat_type_name = serializers.CharField(source='stat_type.name', read_only=True)
    stat_type_code = serializers.CharField(source='stat_type.code', read_only=True)

    class Meta:
        model = FormulaComponent
        fields = ['id', 'stat_type_id', 'stat_type', 'stat_type_name', 'stat_type_code']
        extra_kwargs = {
            'stat_type': {'write_only': True}
        }

class FormulaSerializer(serializers.ModelSerializer):
    components = FormulaComponentSerializer(many=True, required=False)
    sport_name = serializers.CharField(source='sport.name', read_only=True)
    sport_slug = serializers.SlugRelatedField(
        source='sport',
        slug_field='slug',
        queryset=Sport.objects.all(),
        write_only=True
    )

    class Meta:
        model = Formula
        fields = ['id', 'is_ratio', 'uses_point_value', 'decimal_places', 'name', 'expression', 'sport_slug', 'sport_name', 'components']
        extra_kwargs = {
            'sport': {'write_only': True}  # This will be set via sport_slug
        }

    def create(self, validated_data):
        components_data = validated_data.pop('components', [])
        formula = Formula.objects.create(**validated_data)
        
        for component_data in components_data:
            FormulaComponent.objects.create(formula=formula, **component_data)
            
        return formula

    def update(self, instance, validated_data):
        components_data = validated_data.pop('components', None)
        
        # Update all fields, including is_ratio
        instance.name = validated_data.get('name', instance.name)
        instance.expression = validated_data.get('expression', instance.expression)
        instance.is_ratio = validated_data.get('is_ratio', instance.is_ratio)
        instance.uses_point_value = validated_data.get('uses_point_value', instance.uses_point_value)
        instance.decimal_places = validated_data.get('decimal_places', instance.decimal_places)
        instance.sport = validated_data.get('sport', instance.sport)
        instance.save()
        
        if components_data is not None:
            # Handle component updates
            existing_ids = [c['id'] for c in components_data if 'id' in c]
            instance.components.exclude(id__in=existing_ids).delete()
            
            for component_data in components_data:
                component_id = component_data.get('id', None)
                if component_id:
                    component = FormulaComponent.objects.get(id=component_id, formula=instance)
                    component.stat_type = component_data.get('stat_type', component.stat_type)
                    component.save()
                else:
                    FormulaComponent.objects.create(formula=instance, **component_data)
                    
        return instance

class SportStatTypeSerializer(serializers.ModelSerializer):
    sport = serializers.SlugRelatedField(
        queryset=Sport.objects.all(), slug_field="slug"
    )
    expression = serializers.CharField(source="formula.expression", read_only=True)

    class Meta:
        model = SportStatType
        fields = "__all__"

    def validate(self, data):
        errors = {}
        formula = data.get('formula')
        
        if formula and not formula.is_ratio:  # Only validate expression for non-ratio formulas
            try:
                test_vars = {c.stat_type.code: 1 for c in formula.components.all()}
                if formula.expression:  # Only evaluate if expression exists
                    eval(formula.expression, {}, test_vars)
            except Exception as e:
                errors['formula'] = str(e)
        
        if errors:
            raise serializers.ValidationError(errors)
        
        return data

class PositionSerializer(serializers.ModelSerializer):
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

class LeaderCategorySerializer(serializers.ModelSerializer):
    sport_name = serializers.ReadOnlyField(source='sport.name')
    stat_types_count = serializers.SerializerMethodField()
    stat_types_details = serializers.SerializerMethodField()
    
    class Meta:
        model = LeaderCategory
        fields = ['id', 'sport', 'sport_name', 'name', 'display_order', 
                 'stat_types', 'stat_types_count', 'stat_types_details']
        extra_kwargs = {
            'stat_types': {'write_only': True},  # Only used for write operations (POST/PUT)
        }
    
    def get_stat_types_count(self, obj):
        return obj.stat_types.count()
    
    def get_stat_types_details(self, obj):
        return [
            {
                'id': stat.id,
                'name': stat.name,
                'code': stat.code,
                'display_name': stat.display_name
            }
            for stat in obj.stat_types.all()
        ]
    
    def validate(self, data):
        # Check maximum of 4 stats per category during update
        if self.instance and 'stat_types' in self.initial_data:
            stat_types = self.initial_data.get('stat_types', [])
            if len(stat_types) > 4:
                raise serializers.ValidationError({"stat_types": "Maximum of 4 stats per leader category allowed."})
        
        return data

