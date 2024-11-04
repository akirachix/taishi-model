from django.contrib import admin

# Register your models here.
from .models import Case_matching


@admin.register(Case_matching)
class Case_matchingAdmin(admin.ModelAdmin):
    list_display = ['transcription', 'date_created']
    readonly_fields = ['case']

