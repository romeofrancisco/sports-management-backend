from django.contrib import admin
from teams.models import Team, Coach
from .models import TrainingCategory, TrainingSession, PlayerTraining, TrainingMetric, PlayerMetricRecord

@admin.register(TrainingCategory)
class TrainingCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name', 'description')

class PlayerTrainingInline(admin.TabularInline):
    model = PlayerTraining
    extra = 0
    # Removed autocomplete_fields for player as it's an external model

@admin.register(TrainingSession)
class TrainingSessionAdmin(admin.ModelAdmin):
    list_display = ('title', 'date', 'team', 'coach', 'training_type', 'location', 'duration_minutes')
    list_filter = ('date', 'training_type', 'team', 'coach', 'categories')
    search_fields = ('title', 'description', 'location')
    date_hierarchy = 'date'
    filter_horizontal = ('categories',)
    # Removed autocomplete_fields for team and coach as they're external models
    inlines = [PlayerTrainingInline]
    fieldsets = (
        (None, {
            'fields': ('title', 'description', 'training_type')
        }),
        ('Schedule', {
            'fields': ('date', 'start_time', 'end_time', 'location')
        }),
        ('Team & Coach', {
            'fields': ('team', 'coach')
        }),
        ('Categories', {
            'fields': ('categories',)
        }),
        ('Additional Information', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
    )

class PlayerMetricRecordInline(admin.TabularInline):
    model = PlayerMetricRecord
    extra = 0
    autocomplete_fields = ['metric']

@admin.register(PlayerTraining)
class PlayerTrainingAdmin(admin.ModelAdmin):
    list_display = ('player', 'session', 'attendance_status')
    list_filter = ('attendance_status', 'session__date')
    search_fields = ('player__user__first_name', 'player__user__last_name', 'session__title')
    autocomplete_fields = ['session']  # Removed 'player' as it's an external model
    inlines = [PlayerMetricRecordInline]

@admin.register(TrainingMetric)
class TrainingMetricAdmin(admin.ModelAdmin):
    list_display = ('name', 'unit', 'category', 'is_lower_better')
    list_filter = ('category', 'is_lower_better')
    search_fields = ('name', 'description')
    autocomplete_fields = ['category']

@admin.register(PlayerMetricRecord)
class PlayerMetricRecordAdmin(admin.ModelAdmin):
    list_display = ('get_player_name', 'get_session_date', 'metric', 'value', 'recorded_at')
    list_filter = ('player_training__session__date', 'metric', 'recorded_by')
    search_fields = ('player_training__player__user__first_name', 'player_training__player__user__last_name', 
                    'metric__name', 'notes')
    autocomplete_fields = ['player_training', 'metric']
    date_hierarchy = 'recorded_at'
    
    def get_player_name(self, obj):
        return obj.player_training.player
    get_player_name.short_description = 'Player'
    get_player_name.admin_order_field = 'player_training__player__user__last_name'
    
    def get_session_date(self, obj):
        return obj.player_training.session.date
    get_session_date.short_description = 'Session Date'
    get_session_date.admin_order_field = 'player_training__session__date'
