import time
import os
from django.conf import settings
import assemblyai as aai
import boto3
from botocore.exceptions import NoCredentialsError
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # You can set to DEBUG for more detailed logs

# Add a console handler to display logs in the console (optional: also log to a file)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
from dotenv import load_dotenv
from pyannote.audio import Pipeline

# Load environment variables from the .env file located at the root of the project
load_dotenv()

aai.settings.api_key =  os.getenv("AAI_KEY")

import openai
openai.api_key = os.getenv("OPENAI_API_KEY")

def transcribe_audio_with_retry(audio_file_path, retries=5, delay=2):
    """Transcribes audio using OpenAI Whisper API with retries and exponential backoff."""
    
    for attempt in range(retries):
        try:
            with open(audio_file_path, 'rb') as audio_file:
                print(f"Transcribing file: {audio_file_path} (Attempt {attempt+1})") 

                # Use OpenAI's Whisper model for transcription
                transcription = openai.Audio.transcribe(
                    model="whisper-1", 
                    file=audio_file,
                    language="en"
                )

                if 'error' in transcription:
                    print(f"Transcription Error: {transcription['error']}") 
                    raise ValueError(f"Transcription Error: {transcription['error']}")

                print(f"Transcription completed for file: {audio_file_path}") 
                return transcription['text']

        except Exception as e:
            print(f"Error transcribing file {audio_file_path}: {e}") 
            if attempt < retries - 1:
                print(f"Retrying in {delay ** attempt} seconds.") 
                time.sleep(delay ** attempt)
            else:
                print(f"All attempts failed for file: {audio_file_path}")
                return None





# Initialize the diarization pipeline (use your Hugging Face access token if needed)
HF_AUTH_TOKEN = os.getenv('HF_AUTH_TOKEN')
pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=HF_AUTH_TOKEN)


def diarize_audio_with_retry(audio_file_path, retries=5, delay=2):
    """Performs diarization and transcription on the given audio file with retry logic using pyannote.audio and OpenAI."""
    
    # Check if the audio file exists
    if not os.path.exists(audio_file_path):
        logger.error(f"Audio file {audio_file_path} does not exist.")
        return None

    for attempt in range(retries):
        try:
            logger.info(f"Starting diarization for file: {audio_file_path} (Attempt {attempt+1})")
            
            # Try to perform diarization with the pipeline
            try:
                diarization_result = pipeline(audio_file_path)
                logger.info(f"Diarization completed for file: {audio_file_path}")
            except Exception as e:
                logger.error(f"Error during diarization of file {audio_file_path}: {e}")
                raise ValueError(f"Failed to perform diarization: {e}")
            
            # Attempt to transcribe the audio file
            try:
                with open(audio_file_path, 'rb') as audio_file:
                    transcription_response = openai.Audio.transcribe(
                        model="whisper-1",
                        file=audio_file,
                        language="en"
                    )
                    transcription_text = transcription_response.get('text', '')
                
                if not transcription_text:
                    raise ValueError(f"No transcription found for {audio_file_path}")
                logger.info(f"Transcription completed for file: {audio_file_path}")
            
            except Exception as e:
                logger.error(f"Error during transcription of file {audio_file_path}: {e}")
                raise ValueError(f"Failed to transcribe: {e}")

            # Align diarization results with transcription text
            try:
                speaker_texts = align_diarization_with_transcription(diarization_result, transcription_text)
                logger.info(f"Transcription and diarization aligned for file: {audio_file_path}")
                return speaker_texts
            except Exception as e:
                logger.error(f"Error during alignment of diarization with transcription for {audio_file_path}: {e}")
                raise ValueError(f"Failed to align diarization with transcription: {e}")
            
        except Exception as e:
            # Log the error and retry after the specified delay
            logger.error(f"Error processing {audio_file_path}: {e}")
            if attempt < retries - 1:
                wait_time = delay ** attempt
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"All attempts failed for diarization of file: {audio_file_path}")
                return None


def align_diarization_with_transcription(diarization_result, transcription_text):
    """Aligns transcription text with speaker segments based on diarization results."""
    words = transcription_text.split() 
    word_index = 0
    speaker_texts = []
    current_speaker = None
    current_speaker_text = []

    for turn, _, speaker in diarization_result.itertracks(yield_label=True):

        # Estimating the number of words for this segment based on its length
        segment_duration = turn.end - turn.start
        segment_word_count = int(len(words) * (segment_duration / diarization_result.get_timeline().extent().duration))

        # Get the words for this segment and move the index forward
        segment_words = words[word_index:word_index + segment_word_count]
        segment_text = " ".join(segment_words)

        # If the speaker is the same as the previous one, concatenate the text
        if speaker == current_speaker:
            current_speaker_text.append(segment_text)
        else:
            # If we switched speakers, store the current speaker's text and start a new block
            if current_speaker is not None:
                speaker_texts.append({
                    "speaker": current_speaker,
                    "text": " ".join(current_speaker_text)
                })

            # Start a new speaker block
            current_speaker = speaker
            current_speaker_text = [segment_text]

        word_index += segment_word_count

    # Append the last speaker's text after loop ends
    if current_speaker is not None:
        speaker_texts.append({
            "speaker": current_speaker,
            "text": " ".join(current_speaker_text)
        })

    return speaker_texts


def format_diarization(diarization_data):
    """Formats diarization data to include simplified speaker labels and their spoken text."""
    formatted_data = []
    for index, utterance in enumerate(diarization_data):
        speaker = f"Speaker {index + 1}" 
        text = utterance['text'] 
        formatted_data.append(f"{speaker}: {text}\n\n") 

    return ''.join(formatted_data)




    
import assemblyai as aai
from fpdf import FPDF
import json
import re


def extract_case_info_from_transcription(transcription_text):
    logger.info(f"transcription_text:: {transcription_text}")
    prompt = """
    From this court hearing transcription provided, extract the following information:
    "case_title, case_number, judge_name, accused_name, filtered_transcript, court_type, country, court_location, date, prosecutor_name, defense_counsel_name, charges, plea, verdict, sentence, mitigating_factors, aggravating_factors, legal_principles, precedents_cited"

    For the following fields, provide more detailed and comprehensive information:

    1. charges: List all charges in detail, including the specific laws or statutes violated.
    2. plea: Describe the plea entered for each charge, including any explanations or context provided.
    3. verdict: Provide the verdict for each charge, including any reasoning given by the court.
    4. sentence: Detail the full sentence, including any fines, imprisonment terms, probation, or other penalties for each charge.
    5. mitigating_factors: Elaborate on each mitigating factor considered by the court, including how it influenced the decision.
    6. aggravating_factors: Explain each aggravating factor in detail, including its impact on the court's decision.
    7. legal_principles: Provide a comprehensive explanation of each legal principle applied, formatted as numbered paragraphs. Each principle should start with its name in bold, followed by a colon and its explanation.
    8. precedents_cited: For each precedent, include the case name, citation, and a brief explanation of how it relates to the current case.

    Return a valid JSON blob with key-value pairs. Format the detailed fields as follows:

    {
    "case_title": ".....",
    "case_number": ".....",
    ...
    "charges": "1. [Charge 1]: [Detailed description]\\n2. [Charge 2]: [Detailed description]\\n...",
    "plea": "[Detailed description of plea(s)]",
    "verdict": "[Comprehensive verdict description]",
    "sentence": "[Detailed sentence information]",
    "mitigating_factors": "1. [Factor 1]: [Detailed explanation]\\n2. [Factor 2]: [Detailed explanation]\\n...",
    "aggravating_factors": "1. [Factor 1]: [Detailed explanation]\\n2. [Factor 2]: [Detailed explanation]\\n...",
    "legal_principles": "1. [b]Principle 1[/b]: [Detailed explanation]\\n2. [b]Principle 2[/b]: [Detailed explanation]\\n...",
    "precedents_cited": "1. [Case name] ([Citation]): [Brief explanation of relevance]\\n2. [Case name] ([Citation]): [Brief explanation of relevance]\\n..."
    }

    For the filtered_transcript, provide detailed information as a single string value with paragraphs separated by newline characters (\\n).

    Ensure that all multi-line values are returned as a single string with appropriate newline characters.

    For all fields that involve legal references (charges, legal_principles, precedents_cited), enclose penal code sections, case names, and key legal phrases in [b][/b] tags for bolding.
    When displaying the values of the json, make them into capital case except for the detailed fields (filtered_transcript, mitigating_factors, etc.).
    Where there's no information, replace with "......." ensure all keys are in small letters.

    NB: Only return the object nothing else
    """

    result = aai.Lemur().task(
        prompt, 
        final_model=aai.LemurModel.claude3_5_sonnet, 
        input_text=transcription_text,
         max_output_size=4000)
    logger.info(f"result:::::{result}******")

    try:
        return json.loads(result.response)
    except json.JSONDecodeError:
        logger.error("Error: The response is not a valid JSON. Raw response:")
        logger.info(f"@@@{result.response}@@@")
        return {}
    




def format_case_brief(case_info):

    logger.info(f"!!!!!!!!!{case_info}!!!!!!!")
    # Format the header
    header = f"""
    REPUBLIC OF {case_info.get('country', '.......').upper()}

    IN THE HIGH COURT OF {case_info.get('court_location', '.......').upper()}

    CRIMINAL CASE NO. {case_info.get('case_number', '.......')}

    REPUBLIC ......................................... PROSECUTOR

    VERSUS

    {case_info.get('accused_name', '.......')} .......................... ACCUSED

    RULING
    """

    # Format the content in paragraph form
    content = f""" This court is presiding over the case of {case_info.get('case_title', '.......')}, Criminal Case No. {case_info.get('case_number', '.......')}. The prosecution is represented by {case_info.get('prosecutor_name', '.......')}, and the defense counsel is {case_info.get('defense_counsel_name', '.......')}. The accused, {case_info.get('accused_name', '.......')}, has been charged with the following: {case_info.get('charges', '.......')}  The accused entered a plea of {case_info.get('plea', '.......')}. After careful consideration of the evidence presented, this court has reached the following verdict: {case_info.get('verdict', '.......')}  {case_info.get('filtered_transcript', '.......')}  After thorough examination of the case, the court has identified the following mitigating factors: {case_info.get('mitigating_factors', '.......')}  The court has also taken into account the following aggravating factors: {case_info.get('aggravating_factors', '.......')}  In reaching this decision, the court considered the following legal principles: {case_info.get('legal_principles', '.......')}  The court also took into account the following precedents: {case_info.get('precedents_cited', '.......')}  Taking all factors into consideration, this court hereby sentences the accused as follows: {case_info.get('sentence', '.......')} """

    # Format the footer
    footer = f""" DATED, SIGNED AND DELIVERED AT {case_info.get('court_location', '.......')}  THIS {case_info.get('date', '.......')}  {case_info.get('judge_name', '.......')}  JUDGE """

    return header.strip() + "\n\n" + content.strip() + "\n\n" + footer.strip()




def save_as_pdf(brief, filename, image_path=None):
    start_time = time.time()  # Track start time
    
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Add logo image if provided
    if image_path:
        pdf.image(image_path, x=(pdf.w - 40) / 2, y=10, w=40, h=40)
    
    logging.debug("Added logo image (if any).")
    pdf.ln(50)

    # Split the brief into header and content parts more efficiently
    logging.debug("Starting to split the brief into sections.")
    section_split_start = time.time()
    sections = brief.split('RULING ON SENTENCE')

    # Log the time it took to split the sections
    section_split_end = time.time()
    logging.debug(f"Section split took {section_split_end - section_split_start:.4f} seconds.")
    
    # If 'RULING ON SENTENCE' is found, split; otherwise, use the whole content
    header = sections[0].strip() if len(sections) > 1 else ''
    ruling = sections[1].strip() if len(sections) > 1 else sections[0].strip()

    # Add header part to PDF
    logging.debug("Starting to add header to PDF.")
    header_start_time = time.time()
    pdf.set_font("Times", style='B', size=13)
    if header:
        for line in header.split('\n'):
            pdf.cell(0, 10, line.strip(), align='C', ln=True)
        pdf.ln(10)
    header_end_time = time.time()
    logging.debug(f"Adding header took {header_end_time - header_start_time:.4f} seconds.")

    # Add "RULING ON SENTENCE" if it's present in the text
    if len(sections) > 1:
        logging.debug("Adding 'RULING ON SENTENCE' section.")
        pdf.cell(0, 10, 'RULING ON SENTENCE', align='C', ln=True)
        pdf.ln(10)

    # Add content after "RULING ON SENTENCE"
    logging.debug("Starting to add content to PDF.")
    content_start_time = time.time()
    pdf.set_font("Times", size=12)
    content = ruling.split('DATED, SIGNED AND DELIVERED')[0].strip()
    
    # Function to add text with bold formatting
    def add_text_with_bold(pdf, text):
        parts = re.split(r'(\[b\].*?\[/b\])', text)
        for part in parts:
            if part.startswith('[b]') and part.endswith('[/b]'):
                pdf.set_font("Times", style='B', size=12)
                pdf.multi_cell(0, 10, part[3:-4], align='J')  # Bold part
            else:
                pdf.set_font("Times", size=12)
                pdf.multi_cell(0, 10, part, align='J')  # Regular text

    add_text_with_bold(pdf, content)
    content_end_time = time.time()
    logging.debug(f"Adding content took {content_end_time - content_start_time:.4f} seconds.")

    pdf.ln(10)

    # Add footer text if available
    logging.debug("Checking for footer and adding it if present.")
    footer_parts = ruling.split('DATED, SIGNED AND DELIVERED')
    if len(footer_parts) > 1:
        pdf.set_font("Times", style='B', size=13)
        footer = 'DATED, SIGNED AND DELIVERED' + footer_parts[1]
        for line in footer.split('\n'):
            pdf.cell(0, 10, line.strip(), align='C', ln=True)

    # Output the PDF to the file path
    pdf_output_start_time = time.time()
    pdf.output(filename)
    pdf_output_end_time = time.time()
    logging.debug(f"PDF output took {pdf_output_end_time - pdf_output_start_time:.4f} seconds.")

    # Total time taken
    total_time = time.time() - start_time
    logging.debug(f"Total time for generating PDF: {total_time:.4f} seconds.")



def upload_file_to_s3(file, file_name):
    s3_client = boto3.client('s3', 
                             aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                             aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                             region_name=settings.AWS_S3_REGION_NAME)

    try:
        # Log to verify file and file_name
        print(f"Uploading file: {file_name}")
        print(f"File type: {type(file)}")  # Should be <class 'django.core.files.uploadedfile.InMemoryUploadedFile'>

        s3_client.upload_fileobj(file, settings.AWS_STORAGE_BUCKET_NAME, file_name)
        file_url = f"https://{settings.AWS_STORAGE_BUCKET_NAME}.s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com/{file_name}"

        return file_url
    except NoCredentialsError:
        raise ValueError("Credentials not available")
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        raise


