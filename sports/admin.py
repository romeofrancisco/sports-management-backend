from django.contrib import admin
from .models import Sport, Position, SportStatType, Formula, FormulaComponent

admin.site.register(Sport)
admin.site.register(Position)


class FormulaComponentInline(admin.TabularInline):
    model = FormulaComponent
    extra = 1

@admin.register(Formula)
class FormulaAdmin(admin.ModelAdmin):
    inlines = [FormulaComponentInline]
    list_display = ('name', 'sport', 'expression')
    list_filter = ('sport',)

@admin.register(SportStatType)
class SportStatTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_name', 'code', 'is_record', 'is_counter', 'is_box_score', 'is_player_summary', 'is_team_summary', 'get_formula_name')
    list_filter = ('sport', 'is_record', 'is_counter', 'is_box_score', 'is_player_summary', 'is_team_summary')

    def get_formula_name(self, obj):
        return obj.formula.expression if obj.formula else '-'
    get_formula_name.short_description = 'Formula'
