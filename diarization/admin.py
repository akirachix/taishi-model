from django.contrib import admin

# Register your models here.
from diarization.models import DiarizedSegment


@admin.register(DiarizedSegment)
class DiarizedSegmentAdmin(admin.ModelAdmin):
    list_display = ['transcription']  # Display the transcription and creation date
    search_fields = ['transcription__case_name', 'transcription__case_number']  # Search by transcription details
    readonly_fields = ['diarization_data']  # Make diarization_data read-only

    # Display full diarization data and make it read-only
    fields = ['transcription', 'diarization_data']

