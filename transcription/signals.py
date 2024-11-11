from django.db.models.signals import post_save
from django.dispatch import receiver
from pydub import AudioSegment
from transcription.models import Transcription
from transcription_chunks.models import AudioChunk
import boto3
import tempfile

@receiver(post_save, sender=Transcription)
def auto_chunk_audio(sender, instance, created, **kwargs):
    """Chunks the audio file when a new Transcription is created."""
    print(f"Signal received for Transcription: {instance.id}")  # Debugging line
    
    if created and instance.audio_file and not instance.is_chunked:
        try:
            # Download the file from S3 (if it's stored in S3)
            s3_client = boto3.client('s3')
            bucket_name = 'taishibucket'
            file_path = instance.audio_file.name  # Assuming it's stored in S3
            
            # Create a temporary file to hold the downloaded audio
            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                s3_client.download_fileobj(bucket_name, file_path, tmp_file)
                tmp_file.close()  # Close the file to avoid read issues

                # Load the audio from the temporary file
                audio = AudioSegment.from_file(tmp_file.name)

            chunk_length_ms = 2 * 60 * 1000  # Chunk size of 2 minutes (120000 ms)
            chunks = [audio[i:i + chunk_length_ms] for i in range(0, len(audio), chunk_length_ms)]

            # Create an AudioChunk object for each chunk
            for index, chunk in enumerate(chunks):
                chunk_file_path = f"audio_chunks/{instance.id}_chunk_{index}.wav"
                
                # Export chunk to a temporary file or directly to S3
                chunk.export(chunk_file_path, format="wav")

                # Optionally, upload chunk to S3 (if needed)
                s3_chunk_path = f"audio_chunks/{instance.id}_chunk_{index}.wav"
                s3_client.upload_file(chunk_file_path, bucket_name, s3_chunk_path)

                AudioChunk.objects.create(
                    transcription=instance,
                    chunk_file=s3_chunk_path,  # Store S3 path instead of local file path
                    chunk_index=index
                )

                print(f"Created chunk {index} for transcription {instance.id}")  # Debugging line

            # Update transcription status
            instance.is_chunked = True
            instance.status = 'in_progress'
            instance.save(update_fields=['is_chunked', 'status'])

        except Exception as e:
            instance.status = 'failed'
            instance.save(update_fields=['status'])
            print(f"Error chunking audio file for transcription {instance.id}: {e}")
