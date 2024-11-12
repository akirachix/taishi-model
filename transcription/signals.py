import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from pydub import AudioSegment
from transcription.models import Transcription
from transcription_chunks.models import AudioChunk

# Set up logging directly in the code
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Set the logging level

# Create a stream handler to log to the console (stdout)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)  # You can adjust the level as needed

# Create a formatter and set it for the handler
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)

# Add the handler to the logger
logger.addHandler(console_handler)

@receiver(post_save, sender=Transcription)
def auto_chunk_audio(sender, instance, created, **kwargs):
    """Chunks the audio file when a new Transcription is created."""
    logger.debug(f"Signal received for Transcription: {instance.id}")  # Log when signal is received
    
    if created and instance.audio_file and not instance.is_chunked:
        try:
            # Load the audio file
            logger.info(f"Loading audio file for transcription {instance.id} from {instance.audio_file.path}")
            audio = AudioSegment.from_file(instance.audio_file.path)
            chunk_length_ms = 2 * 60 * 1000  # Chunk size of 2 minutes
            chunks = [audio[i:i + chunk_length_ms] for i in range(0, len(audio), chunk_length_ms)]

            # Create an AudioChunk object for each chunk
            for index, chunk in enumerate(chunks):
                chunk_file_path = f"audio_chunks/{instance.id}_chunk_{index}.wav"
                logger.info(f"Exporting chunk {index} to {chunk_file_path}")
                chunk.export(chunk_file_path, format="wav")

                AudioChunk.objects.create(
                    transcription=instance,
                    chunk_file=chunk_file_path,
                    chunk_index=index
                )
                logger.debug(f"Created chunk {index} for transcription {instance.id}")

            # Update transcription status
            logger.info(f"Updating transcription status for {instance.id} to 'in_progress'")
            instance.is_chunked = True
            instance.status = 'in_progress'
            instance.save(update_fields=['is_chunked', 'status'])

        except Exception as e:
            logger.error(f"Error chunking audio file for transcription {instance.id}: {e}")
            instance.status = 'failed'
            instance.save(update_fields=['status'])
