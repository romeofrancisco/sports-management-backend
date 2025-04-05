from django.contrib import admin
from .models import Sport, Position, SportStatType

admin.site.register(Sport)
admin.site.register(Position)
@admin.register(SportStatType)
class SportStatTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'abbreviation')
