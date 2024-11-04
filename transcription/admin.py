from django.contrib import admin

# Register your models here.
from .models import Transcription

@admin.register(Transcription)
class TranscriptionAdmin(admin.ModelAdmin):
    list_display = ['case_name','case_number','status', 'audio_file', 'date_created']
    readonly_fields = ['transcription_text']  # Make transcription_text read-only

