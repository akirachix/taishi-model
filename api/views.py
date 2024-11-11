from django.shortcuts import render

# Create your views here.

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
from case_brief.models import CaseBrief
import os
from django.conf import settings
import subprocess
from django.http import HttpResponse
from .utils import *


def check_ffmpeg(request):
    ffmpeg_check = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
    return HttpResponse(f"FFmpeg Version:\n{ffmpeg_check.stdout}")

class TranscriptionViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    queryset = Transcription.objects.all()
    serializer_class = TranscriptionSerializer
    
    def create(self, request, *args, **kwargs):
        """Handle audio file upload, process transcription, and delete file."""
        file = request.FILES['audio_file']
        file_name = f"transcription/{file.name}"
        
        # Upload file to S3
        file_url = upload_file_to_s3(file, file_name)
        
        # Save the file URL in the database
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            transcription = serializer.save(audio_file=file_url)
            return Response({
                'id': transcription.id,
                'message': 'Transcription processed successfully.',
                'status': transcription.status,
                'transcription_text': transcription.transcription_text,
            }, status=201)

        return Response(serializer.errors, status=400)

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
            search_term = ' '.join(extracted_details)

            case_laws = scrape_case_laws(search_term)

            # Create a new Case_matching instance
            case_matching = Case_matching.objects.create(
                transcription=transcription,
                case={"details": extracted_details, "related_cases": case_laws}
            )
            
            serializer = CaseMatchingSerializers(case_matching)
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




from django.shortcuts import render, get_object_or_404, redirect
from transcription.models import Transcription


def generate_case_brief_view(request, transcription_id):
    transcription = get_object_or_404(Transcription, id=transcription_id)

    # Generate PDF file for the case brief
    pdf_filename = f"case_brief_{transcription.case_number}.pdf"
    image_path = "/home/student/Downloads/themis_logo.png"  

    # Redirect or render a success message (based on your requirement)
    return redirect('case_brief_success')



def download_case_brief_pdf(request, transcription_id):
    try:
        # Retrieve the CaseBrief object using transcription_id
        case_brief = CaseBrief.objects.get(transcription__id=transcription_id)
        
        # Ensure there’s a path to the saved PDF
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



class CaseBriefSegmentListCreateView(generics.ListCreateAPIView):
    """
    Handles the creation and listing of casebriefs.
    """
    queryset = CaseBrief.objects.all()
    serializer_class = CaseBriefSerializer


class CaseBriefDetailView(generics.ListAPIView):
    """
    Retrieve case briefs for a specific transcription.
    """
    serializer_class = CaseBriefSerializer

    def get_queryset(self):
        transcription_id = self.kwargs['pk']
        return CaseBrief.objects.filter(transcription_id=transcription_id)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        if queryset.exists():
            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response({"error": "No case briefs found for this transcription"}, status=status.HTTP_404_NOT_FOUND)

