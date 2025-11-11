"""
This script adds new training metrics to the database for simulations.
"""
from django.core.management.base import BaseCommand
from trainings.models import TrainingCategory, TrainingMetric, MetricUnit
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Add new basketball metrics to the database'

    def handle(self, *args, **options):
        # First, check or create categories
        categories = self._ensure_basketball_categories()
        
        # Then add the metrics
        self._add_basketball_metrics(categories)
        
        self.stdout.write(self.style.SUCCESS('Successfully added basketball metrics'))

    def _ensure_basketball_categories(self):
        """Ensure we have the required training categories for basketball"""
        # find an admin user to attribute created_by
        admin = User.objects.filter(is_superuser=True).first()
        admin_id = admin.pk if admin else None

        categories_data = [
            {"name": "Endurance", "description": "Activities focused on stamina and cardiovascular fitness", "created_by": admin},
            {"name": "Agility", "description": "Quick movements and direction changes", "created_by": admin},
            {"name": "Speed", "description": "Sprint and acceleration training", "created_by": admin},
            {"name": "Technique", "description": "Sport-specific skill development", "created_by": admin},
            {"name": "Explosiveness", "description": "Power and explosive strength development", "created_by": admin},
            {"name": "Strength", "description": "Weight training and resistance exercises", "created_by": admin},
        ]
        
        # Dictionary to store created/existing categories by name
        category_dict = {}
        
        for data in categories_data:
            obj, created = TrainingCategory.objects.get_or_create(
                name=data["name"],
                defaults={"description": data["description"], "created_by": data["created_by"]}
            )
            if created:
                self.stdout.write(f'Created category: {obj.name}')
            else:
                self.stdout.write(f'Using existing category: {obj.name}')
            
            category_dict[obj.name] = obj
            
        return category_dict

    def _ensure_metric_units(self):
        """Create required MetricUnit objects if they don't exist"""
        unit_data = {
            "seconds": {"name": "Seconds", "weight": 1.0},
            "in": {"name": "Inches", "weight": 1.0},
            "reps": {"name": "Repetitions", "weight": 0.2},
            "kg": {"name": "Kilograms", "weight": 1.0},
            "m": {"name": "Meters", "weight": 1.0},
        }
        
        # find admin for attribution
        admin = User.objects.filter(is_superuser=True).first()
        admin_id = admin.pk if admin else None

        units = {}
        for code, data in unit_data.items():
            unit, created = MetricUnit.objects.get_or_create(
                code=code,
                defaults={
                    "name": data["name"],
                    "normalization_weight": data["weight"],
                    "description": f"Unit for {data['name']}",
                    "created_by": admin,
                }
            )
            units[code] = unit
            if created:
                self.stdout.write(f'Created unit: {unit.name}')
            else:
                self.stdout.write(f'Using existing unit: {unit.name}')
        
        return units

    def _add_basketball_metrics(self, categories):
        """Add basketball-specific metrics"""
        # First ensure all required units exist
        units = self._ensure_metric_units()
        
        metrics_data = [
            {
                "name": "3/4 Court Sprint",
                "description": "Sprint time from baseline to opposite free-throw line (¾ court).",
                "metric_unit": units["seconds"],
                "category": "Speed",
                "is_lower_better": True
            },
            {
                "name": "Vertical Jump",
                "description": "Assesses an individual's lower body power, specifically their ability to jump vertically.",
                "metric_unit": units["in"],
                "category": "Explosiveness",
                "is_lower_better": False
            },
            {
                "name": "Bench Press Reps (185 lbs)",
                "description": "Repetitions completed at 185 pounds.",
                "metric_unit": units["reps"],
                "category": "Strength",
                "is_lower_better": False
            },
            {
                "name": "Squat Max",
                "description": "Maximum weight lifted in a back squat.",
                "metric_unit": units["kg"],
                "category": "Strength",
                "is_lower_better": False
            },
            {
                "name": "Yo-Yo Intermittent Recovery Test",
                "description": "Total distance or level reached in Yo-Yo test.",
                "metric_unit": units["m"],
                "category": "Endurance",
                "is_lower_better": False
            },
            {
                "name": "Suicide Drill Time",
                "description": "Total time to complete a full suicide run across the court.",
                "metric_unit": units["seconds"],
                "category": "Endurance",
                "is_lower_better": True
            },
            {
                "name": "Shuttle Run (5-10-5)",
                "description": "Pro agility drill measuring quick direction changes.",
                "metric_unit": units["seconds"],
                "category": "Agility",
                "is_lower_better": True
            }
        ]
        
        metrics_created = 0
        
        for data in metrics_data:
            category_name = data.pop("category")
            if category_name in categories:
                # Check if the metric already exists
                exists = TrainingMetric.objects.filter(name=data["name"]).exists()
                
                if not exists:
                    # Create the metric
                    data["category"] = categories[category_name]
                    metric = TrainingMetric.objects.create(**data)
                    self.stdout.write(f'Created metric: {metric.name}')
                    metrics_created += 1
                else:
                    self.stdout.write(f'Metric already exists: {data["name"]}')
            else:
                self.stdout.write(self.style.WARNING(f'Category {category_name} not found, skipping metric'))
        
        self.stdout.write(f'Created {metrics_created} new metrics')
