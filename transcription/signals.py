import os
import logging
from pydub import AudioSegment
from django.db.models.signals import post_save
from django.dispatch import receiver
from transcription.models import Transcription
from transcription_chunks.models import AudioChunk

# Set the path explicitly for pydub
os.environ["PATH"] += ":/usr/local/bin"
AudioSegment.ffmpeg = "/usr/local/bin/ffmpeg"
AudioSegment.ffprobe = "/usr/local/bin/ffprobe"

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Set to desired log level

# Create a handler to log to the console (stdout)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)

# Create a formatter and set it for the handler
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)

# Add the handler to the logger
logger.addHandler(console_handler)

@receiver(post_save, sender=Transcription)
def auto_chunk_audio(sender, instance, created, **kwargs):
    """Chunks the audio file when a new Transcription is created."""
    logger.debug(f"Signal received for Transcription: {instance.id}")  # Debugging line

    if created and instance.audio_file and not instance.is_chunked:
        try:
            # Check if the audio file exists
            audio_file_path = instance.audio_file.path
            if not os.path.exists(audio_file_path):
                raise FileNotFoundError(f"Audio file does not exist at {audio_file_path}")

            # Load the audio file
            logger.debug(f"Loading audio file for transcription {instance.id} from {audio_file_path}")
            audio = AudioSegment.from_file(audio_file_path)

            chunk_length_ms = 2 * 60 * 1000  # Chunk size of 2 minutes (adjust as needed)
            chunks = [audio[i:i + chunk_length_ms] for i in range(0, len(audio), chunk_length_ms)]

            # Create an AudioChunk object for each chunk
            for index, chunk in enumerate(chunks):
                chunk_file_path = f"audio_chunks/{instance.id}_chunk_{index}.wav"
                chunk.export(chunk_file_path, format="wav")

                AudioChunk.objects.create(
                    transcription=instance,
                    chunk_file=chunk_file_path,
                    chunk_index=index
                )

                logger.debug(f"Created chunk {index} for transcription {instance.id}")

            # Update transcription status
            instance.is_chunked = True
            instance.status = 'in_progress'
            instance.save(update_fields=['is_chunked', 'status'])

        except FileNotFoundError as e:
            instance.status = 'failed'
            instance.save(update_fields=['status'])
            logger.error(f"FileNotFoundError while processing transcription {instance.id}: {str(e)}")

        except Exception as e:
            instance.status = 'failed'
            instance.save(update_fields=['status'])
            logger.error(f"Error chunking audio file for transcription {instance.id}: {str(e)}")

        # Additional logging for troubleshooting
        logger.debug(f"Finished processing transcription {instance.id}.")
