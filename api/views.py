from rest_framework import generics, viewsets, status, mixins
from .serializers import TranscriptionSerializer, DiarizedSegmentSerializer, AudioChunkSerializer, CaseMatchingSerializers,CaseBriefSerializer
from transcription.models import Transcription
from diarization.models import DiarizedSegment
from transcription_chunks.models import AudioChunk
from case_matching.models import Case_matching
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.exceptions import NotFound
from case_matching.signals import scrape_case_laws, extract_case_details
from django.db.models import Count
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.conf import settings
from case_brief.models import *
import os
from django.core.files.storage import default_storage
import logging
from pydub import AudioSegment
import requests
import traceback
import subprocess



logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # You can set to DEBUG for more detailed logs

# Add a console handler to display logs in the console (optional: also log to a file)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

class TranscriptionViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    This viewset provides `list`, `create`, and `retrieve` actions for Transcriptions.
    """
    queryset = Transcription.objects.all()
    serializer_class = TranscriptionSerializer
    parser_classes = [MultiPartParser, FormParser]


    def create(self, request, *args, **kwargs):
        """
        Handle audio file upload and trigger transcription.
        """
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            transcription = serializer.save()

            # Access the uploaded file's path
            audio_file_path = transcription.audio_file.path
            logger.info(f"Attempting to load audio file from: {audio_file_path}")

            # Check if the file exists
            if not os.path.exists(audio_file_path):
                logger.error(f"Audio file does not exist at: {audio_file_path}")
                return Response({
                    'message': 'Audio file not found.',
                }, status=status.HTTP_404_NOT_FOUND)

            # Log file size for further debugging
            file_size = os.path.getsize(audio_file_path)
            logger.info(f"Audio file size: {file_size} bytes")

            # Log file content type
            file_content_type = request.FILES['audio_file'].content_type
            logger.info(f"File content type: {file_content_type}")

            # Set output file path (modify as needed)
            output_file_path = "/home/ec2-user/taishi-model/audio_files/file.wav"  # Adjust this path

            try:
                # Run ffmpeg command with both input and output files
                command = ["ffmpeg", "-v", "error", "-i", audio_file_path, output_file_path]
                result = subprocess.run(command, capture_output=True, text=True)
                
                # Check for FFmpeg errors
                if result.returncode != 0:
                    logger.error(f"FFmpeg error: {result.stderr}")
                    return Response({
                        'message': 'Error processing audio file with FFmpeg.',
                        'error': result.stderr,
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                logger.info(f"FFmpeg output: {result.stdout}")
                
                # Attempt to load the audio file using AudioSegment
                audio = AudioSegment.from_file(audio_file_path)
                logger.info(f"Audio file loaded successfully: {audio_file_path}")
            except Exception as e:
                logger.error(f"Error loading audio file {audio_file_path}: {str(e)}")
                return Response({
                    'message': 'Error processing audio file.',
                    'error': str(e),
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Return the response after processing
            return Response({
                'id': transcription.id,
                'message': 'Transcription processed successfully.',
                'status': transcription.status,
                'transcription_text': transcription.transcription_text,
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


    @action(detail=True, methods=['get'])
    def get_transcription(self, request, pk=None):
        """
        Return the transcription status and text.
        """
        transcription = self.get_object()
        return Response({
            'id': transcription.id,
            'status': transcription.status,
            'transcription_text': transcription.transcription_text,
        })
        
        
        
    @action(detail=False, methods=['get'])
    def transcription_status_counts(self, request):
        """
        Return the count of transcriptions with statuses 'completed' and 'pending'.
        """
        counts = Transcription.objects.values('status').annotate(total=Count('status'))
        completed_count = next((item['total'] for item in counts if item['status'] == 'completed'), 0)
        pending_count = next((item['total'] for item in counts if item['status'] == 'pending'), 0)
        
        return Response({
            'completed': completed_count,
            'pending': pending_count,
        }, status=status.HTTP_200_OK)
        
        



class TranscriptionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Handles retrieving, updating, and deleting a specific transcription.
    """
    queryset = Transcription.objects.all()
    serializer_class = TranscriptionSerializer

    def get_object(self):
        """
        Custom method to get a transcription by ID or raise a 404 error if not found.
        """
        try:
            transcription = Transcription.objects.get(id=self.kwargs['pk'])
            return transcription
        except Transcription.DoesNotExist:
            raise NotFound({"error": "Transcription not found"})


class DiarizedSegmentListCreateView(generics.ListCreateAPIView):
    """
    Handles the creation and listing of diarized segments.
    """
    queryset = DiarizedSegment.objects.all()
    serializer_class = DiarizedSegmentSerializer


class DiarizationDetailView(generics.RetrieveAPIView):
    """
    Retrieve diarization for a specific transcription.
    """
    queryset = DiarizedSegment.objects.all()
    serializer_class = DiarizedSegmentSerializer

    def get(self, request, pk):
        try:
            diarization = DiarizedSegment.objects.get(transcription__id=pk)
            serializer = DiarizedSegmentSerializer(diarization)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except DiarizedSegment.DoesNotExist:
            return Response({"error": "Diarization not found for this transcription"}, status=status.HTTP_404_NOT_FOUND)



class CaseMatchingListView(generics.ListCreateAPIView):
    queryset = Case_matching.objects.all()
    serializer_class = CaseMatchingSerializers

    def post(self, request):
        transcription_id = request.data.get("transcription")
        print(f'ID: {request.data}')

        if not transcription_id:
            return Response({"error": "Transcription ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Extract transcription text using the ID
            transcription = Transcription.objects.get(id=transcription_id)
            transcription_text = transcription.transcription_text

            extracted_details = extract_case_details(transcription_text)
            print(f'extracted_details: {extracted_details}')
            print(f'type of extracted_details: {type(extracted_details)}')  ## ['Ruth Wanjiku Kamande', 'murder', 'family']

            search_term = ' '.join(extracted_details)

            logger.info(f"search_term {search_term} @@@")

            case_laws = scrape_case_laws(search_term)

            logger.info(f"case laws {case_laws} ***")



            # Create a new Case_matching instance
            case_matching = Case_matching.objects.create(
                transcription=transcription,
                case={"details": extracted_details, "related_cases": case_laws}
            )
            logger.info(f"successfully created case macthing record {case_matching}____")

            
            serializer = CaseMatchingSerializers(case_matching)
            logger.info(f"successful @@@@{serializer.data}____")
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Transcription.DoesNotExist:
            return Response({"error": "Transcription not found"}, status=status.HTTP_404_NOT_FOUND)



class CaseMatchingDetailView(generics.RetrieveAPIView):
    queryset = Case_matching.objects.all()
    serializer_class = CaseMatchingSerializers
    def get(self, request, id):
        try:
           case_law = Case_matching.objects.get(transcription_id=id)
           serializer = CaseMatchingSerializers(case_law)
           return Response(serializer.data, status=status.HTTP_200_OK)

        except Case_matching.DoesNotExist:
            return Response({"error": "Diarization not found for this transcription"}, status=status.HTTP_404_NOT_FOUND)


class AudioChunkViewSet(viewsets.ModelViewSet):
    """
    A viewset to handle creating, retrieving, and listing audio chunks.
    """
    queryset = AudioChunk.objects.all()
    serializer_class = AudioChunkSerializer

    def create(self, request, *args, **kwargs):
        """
        Handle uploading a new audio chunk.
        """
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            audio_chunk = serializer.save()
            return Response({
                'id': audio_chunk.id,
                'transcription_id': audio_chunk.transcription.id,
                'chunk_index': audio_chunk.chunk_index,
                'status': audio_chunk.status,
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def retrieve(self, request, *args, **kwargs):
        """
        Return a specific audio chunk.
        """
        chunk = self.get_object()
        return Response({
            'id': chunk.id,
            'transcription_id': chunk.transcription.id,
            'chunk_index': chunk.chunk_index,
            'status': chunk.status,
            'transcription_text': chunk.transcription_text,
            'diarization_data': chunk.diarization_data,
        })

    def list(self, request, *args, **kwargs):
        """
        Return a list of audio chunks.
        """
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)




def download_case_brief_pdf(request, transcription_id):
    try:
        # Retrieve the CaseBrief object using transcription_id
        case_brief = CaseBrief.objects.get(transcription__id=transcription_id)
        
        # Ensure there's a path to the saved PDF
        if case_brief.pdf_file_path and os.path.exists(case_brief.pdf_file_path):
            # Serve the PDF file for download
            return FileResponse(
                open(case_brief.pdf_file_path, 'rb'), 
                as_attachment=True, 
                filename=f'case_brief_{transcription_id}.pdf'
            )
        else:
            raise Http404("PDF file not found.")
    
    except CaseBrief.DoesNotExist:
        raise Http404("Case brief not found for this transcription.")



class CaseBriefSegmentListCreateView(generics.CreateAPIView):
    queryset = CaseBrief.objects.all()
    serializer_class = CaseBriefSerializer

    def get(self, request):
        """
        Retrieve a list of all CaseBrief objects.
        """
        try:
            # Fetch all CaseBrief objects
            case_briefs = CaseBrief.objects.all()

            # Serialize the queryset
            serializer = CaseBriefSerializer(case_briefs, many=True)

            # Return serialized data
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            # Log and handle unexpected errors
            import traceback
            print(f"Unexpected error: {e}")
            print(traceback.format_exc())
            return Response({"error": "Internal server error occurred."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

  

    def post(self, request):
        try:
            # Log incoming request
            print(f"Incoming Request Data: {request.data}")

            # Extract transcription ID from the request
            transcription_id = request.data.get("transcription")
            if not transcription_id:
                return Response({"error": "Transcription ID is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Fetch the transcription object
            try:
                transcription = Transcription.objects.get(id=transcription_id)
            except Transcription.DoesNotExist:
                return Response({"error": "Transcription not found"}, status=status.HTTP_404_NOT_FOUND)

            # Create and generate the case brief
            case_brief = CaseBrief(transcription=transcription)
            case_brief.generate_case_brief()

            # Serialize and return the created case brief
            serializer = CaseBriefSerializer(case_brief)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            # Log the exception and full traceback
            import traceback
            print(f"Unexpected error: {e}")
            print(traceback.format_exc())
            return Response({"error": "Internal server error occurred."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

    def delete(self, request):
        """
        Delete a CaseBrief associated with a specific Transcription ID.
        """
        try:
            transcription_id = request.data.get("transcription")
            if not transcription_id:
                return Response({"error": "Transcription ID is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Fetch the CaseBrief associated with the transcription ID
            case_brief = get_object_or_404(CaseBrief, id=transcription_id)

            # Delete the CaseBrief
            case_brief.delete()

            return Response(
                {"message": f"CaseBrief associated with transcription ID {transcription_id} has been deleted."},
                status=status.HTTP_204_NO_CONTENT,
            )

        except Exception as e:
            import traceback
            print(f"Unexpected error: {e}")
            print(traceback.format_exc())
            return Response({"error": "Internal server error occurred."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        


class CaseBriefDetailView(generics.ListAPIView):
    queryset = CaseBrief.objects.all()
    serializer_class = CaseBriefSerializer
    def get(self, request, id):
        try:
           case_brief = CaseBrief.objects.get(transcription_id=id)
           serializer = CaseBriefSerializer(case_brief)
           return Response(serializer.data, status=status.HTTP_200_OK)

        except CaseBrief.DoesNotExist:
            return Response({"error": "CaseBrief not found for this transcription"}, status=status.HTTP_404_NOT_FOUND)

