from django.db.models.signals import post_save
from django.dispatch import receiver
from pydub import AudioSegment
from transcription.models import Transcription
from transcription_chunks.models import AudioChunk
from django.conf import settings
import boto3
from io import BytesIO

@receiver(post_save, sender=Transcription)
def auto_chunk_audio(sender, instance, created, **kwargs):
    if created and instance.audio_file and not instance.is_chunked:
        try:
            # Initialize the S3 client
            s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_S3_REGION_NAME
            )
            
            # Extract the file name from the S3 URL saved in the model
            bucket_name = settings.AWS_STORAGE_BUCKET_NAME
            file_name = instance.audio_file.name  # This gets the path relative to the bucket
            
            # Fetch the file from S3
            response = s3_client.get_object(Bucket=bucket_name, Key=file_name)
            file_stream = BytesIO(response['Body'].read())

            # Process the audio file (you can use Pydub for audio chunking)
            audio = AudioSegment.from_file(file_stream)
            chunk_length_ms = 2 * 60 * 1000  # Chunk size of 2 minutes
            chunks = [audio[i:i + chunk_length_ms] for i in range(0, len(audio), chunk_length_ms)]

            # Save chunks to your database (AudioChunk model)
            for index, chunk in enumerate(chunks):
                chunk_file_name = f"audio_chunks/{instance.id}_chunk_{index}.wav"
                chunk.export(chunk_file_name, format="wav")

                # Save each chunk in the database
                AudioChunk.objects.create(
                    transcription=instance,
                    chunk_file=chunk_file_name,
                    chunk_index=index
                )

            # Update transcription status
            instance.is_chunked = True
            instance.status = 'in_progress'
            instance.save(update_fields=['is_chunked', 'status'])

        except Exception as e:
            instance.status = 'failed'
            instance.save(update_fields=['status'])
            print(f"Error chunking audio file for transcription {instance.id}: {e}")
