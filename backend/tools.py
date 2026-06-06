import re
import json
import wave
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import pypdf
from youtube_transcript_api import YouTubeTranscriptApi
from mutagen import File as MutagenFile

from backend import config
from backend import llm

# Configure logging
logger = logging.getLogger(__name__)

class ToolExecutionError(Exception):
    """Custom exception raised when a tool execution fails."""
    pass


def get_audio_duration(file_path: Path) -> float:
    """
    Determines audio duration in seconds using wave or mutagen.
    
    Args:
        file_path: Path to the audio file.
        
    Returns:
        Duration of the audio in seconds. Returns 0.0 if unable to calculate.
    """
    # Try wave for WAV format
    if file_path.suffix.lower() == ".wav":
        try:
            with wave.open(str(file_path), "rb") as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                if rate > 0:
                    return float(frames / rate)
        except Exception as e:
            logger.warning(f"Wave duration parser failed: {e}")

    # Fallback to Mutagen for MP3/M4A/WAV metadata
    try:
        audio = MutagenFile(file_path)
        if audio is not None and audio.info is not None:
            return float(audio.info.length)
    except Exception as e:
        logger.warning(f"Mutagen duration parser failed: {e}")

    return 0.0


def ocr_image(file_path: Path, suite: str = "proprietary", model_name: str = "gemini-2.5-flash") -> Dict[str, Any]:
    """
    Performs OCR on an image file.
    
    Args:
        file_path: Path to the image file.
        suite: "proprietary" or "opensource"
        model_name: Selected model ID string.
        
    Returns:
        A dictionary with the extracted transcript and an OCR confidence score.
    """
    try:
        return llm.ocr_image(file_path, suite, model_name)
    except Exception as e:
        logger.error(f"OCR tool failed: {e}")
        raise ToolExecutionError(f"Image OCR failed: {str(e)}")


def ocr_pdf_via_gemini(file_path: Path, suite: str = "proprietary", model_name: str = "gemini-2.5-flash") -> Dict[str, Any]:
    """
    Performs OCR on a PDF document using the Gemini Files API.
    Used as a fallback for scanned PDFs.
    
    Args:
        file_path: Path to the PDF file.
        suite: "proprietary" or "opensource"
        model_name: Selected model ID string.
        
    Returns:
        A dictionary with the extracted text, confidence, and method used.
    """
    if suite == "opensource":
        raise ToolExecutionError(
            "Scanned PDF OCR is not supported in the Open Source suite. "
            "Please switch to the Proprietary suite (Gemini) to process scanned documents."
        )
        
    try:
        # Re-use Gemini OCR implementation in llm.py
        return llm._ocr_gemini_image(file_path, model_name)
    except Exception as e:
        logger.error(f"Gemini PDF OCR fallback failed: {e}")
        raise ToolExecutionError(f"Scanned PDF OCR failed: {str(e)}")


def extract_pdf_text(file_path: Path, suite: str = "proprietary", model_name: str = "gemini-2.5-flash") -> Dict[str, Any]:
    """
    Extracts text from a PDF file. Falls back to OCR if text is empty (scanned PDF).
    
    Args:
        file_path: Path to the PDF file.
        suite: "proprietary" or "opensource"
        model_name: Selected model ID string.
        
    Returns:
        A dictionary containing the extracted text and metadata.
    """
    try:
        reader = pypdf.PdfReader(str(file_path))
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        
        text = text.strip()
        if not text:
            # Scanned PDF detected, run OCR fallback
            logger.info("PDF has no embedded text. Initiating scanned PDF OCR fallback...")
            return ocr_pdf_via_gemini(file_path, suite, model_name)
            
        return {
            "text": text,
            "confidence": 1.0,
            "method": "native_pdf_parser"
        }
    except Exception as e:
        logger.error(f"Native PDF parsing failed, trying OCR fallback. Error: {e}")
        try:
            return ocr_pdf_via_gemini(file_path, suite, model_name)
        except Exception as ocr_err:
            raise ToolExecutionError(f"PDF text extraction failed: {str(ocr_err)}")


def transcribe_audio(file_path: Path, suite: str = "proprietary", model_name: str = "gemini-2.5-flash") -> Dict[str, Any]:
    """
    Transcribes audio files and calculates duration.
    
    Args:
        file_path: Path to the audio file.
        suite: "proprietary" or "opensource"
        model_name: Selected model ID string.
        
    Returns:
        A dictionary with the transcribed text, duration in seconds, and cleanup status.
    """
    try:
        duration = get_audio_duration(file_path)
        result = llm.transcribe_audio(file_path, suite, model_name)
        result["duration"] = round(duration, 2)
        return result
    except Exception as e:
        logger.error(f"Audio transcription failed: {e}")
        raise ToolExecutionError(f"Audio transcription failed: {str(e)}")


def fetch_youtube_transcript(url: str) -> Dict[str, Any]:
    """
    Extracts video ID and retrieves the transcript of a YouTube video.
    
    Args:
        url: YouTube URL string.
        
    Returns:
        Dictionary with transcript text or an error description.
    """
    video_id = None
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
        r"youtu\.be\/([0-9A-Za-z_-]{11})",
        r"embed\/([0-9A-Za-z_-]{11})"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            video_id = match.group(1)
            break
            
    if not video_id:
        return {"error": f"Unable to extract a valid YouTube Video ID from: {url}"}
        
    try:
        api = YouTubeTranscriptApi()
        # Retrieve list of transcripts and fetch the first available one to support auto-generated/non-English fallbacks
        try:
            transcript_list = api.list(video_id)
            data = None
            for transcript in transcript_list:
                data = transcript.fetch()
                break
        except Exception:
            # Fallback to direct fetch
            data = api.fetch(video_id)
            
        if not data:
            return {"error": f"No transcript available for video: {video_id}", "video_id": video_id}
            
        # Parse snippets (handles dictionaries in older versions and FetchedTranscriptSnippet objects in newer versions)
        text_snippets = []
        for item in data:
            if hasattr(item, "text"):
                text_snippets.append(item.text)
            elif isinstance(item, dict) and "text" in item:
                text_snippets.append(item["text"])
            else:
                text_snippets.append(str(item))
                
        full_text = " ".join(text_snippets)
        
        return {
            "text": full_text,
            "video_id": video_id,
            "source_url": url
        }
    except Exception as e:
        logger.error(f"YouTube Transcript API failed: {e}")
        return {"error": f"Failed to fetch YouTube transcript: {str(e)}", "video_id": video_id}


def summarize_text(text: str, suite: str = "proprietary", model_name: str = "gemini-2.5-flash") -> Dict[str, Any]:
    """
    Summarizes content into three distinct formats: 1-line, 3 bullets, and 5-sentence summary.
    
    Args:
        text: Text to summarize.
        suite: "proprietary" or "opensource"
        model_name: Model ID.
        
    Returns:
        Dictionary containing the summaries.
    """
    try:
        prompt = (
            "Analyze the text below. Summarize it in exactly three formats. "
            "Your output must be a JSON object with these keys:\n"
            "1. 'one_line': A single-line summary (maximum 20 words).\n"
            "2. 'three_bullets': A list of exactly 3 bullet points, each summarizing a key insight.\n"
            "3. 'five_sentences': A comprehensive summary of exactly 5 sentences.\n\n"
            f"Text content:\n{text}"
        )
        
        # Define Pydantic Schema structure for parsing (used in Gemini)
        # For OpenAI and Groq we pass the JSON prompt directly.
        class SummarySchema(llm.pydantic.BaseModel):
            one_line: str
            three_bullets: list
            five_sentences: str
            
        res_text = llm.generate_text(
            prompt=prompt,
            system_instruction="You are a precise text summarizer.",
            json_schema=SummarySchema,
            suite=suite,
            model_name=model_name
        )
        
        result = json.loads(res_text)
        return {
            "one_line": result.get("one_line", ""),
            "three_bullets": result.get("three_bullets", []),
            "five_sentences": result.get("five_sentences", "")
        }
    except Exception as e:
        logger.error(f"Summarizer tool failed: {e}")
        raise ToolExecutionError(f"Summarization failed: {str(e)}")


def analyze_sentiment(text: str, suite: str = "proprietary", model_name: str = "gemini-2.5-flash") -> Dict[str, Any]:
    """
    Performs sentiment analysis and returns label, confidence, and justification.
    
    Args:
        text: Text to analyze.
        suite: "proprietary" or "opensource"
        model_name: Model ID.
        
    Returns:
        Dictionary containing sentiment assessment.
    """
    try:
        prompt = (
            "Determine the sentiment of the text below. "
            "Return a JSON object containing:\n"
            "1. 'label': The primary sentiment (Positive, Negative, or Neutral).\n"
            "2. 'confidence': A float between 0.0 and 1.0 reflecting your confidence.\n"
            "3. 'justification': A one-line sentence explaining the reasoning behind this label.\n\n"
            f"Text content:\n{text}"
        )
        
        class SentimentSchema(llm.pydantic.BaseModel):
            label: str
            confidence: float
            justification: str
            
        res_text = llm.generate_text(
            prompt=prompt,
            system_instruction="You are an expert sentiment analyzer.",
            json_schema=SentimentSchema,
            suite=suite,
            model_name=model_name
        )
        
        result = json.loads(res_text)
        return {
            "label": result.get("label", "Neutral"),
            "confidence": float(result.get("confidence", 1.0)),
            "justification": result.get("justification", "")
        }
    except Exception as e:
        logger.error(f"Sentiment analysis tool failed: {e}")
        raise ToolExecutionError(f"Sentiment analysis failed: {str(e)}")


def explain_code(code: str, suite: str = "proprietary", model_name: str = "gemini-2.5-flash") -> Dict[str, Any]:
    """
    Analyzes code snippets to detect language, explain function, discover bugs, and find time complexity.
    
    Args:
        code: Source code string to explain.
        suite: "proprietary" or "opensource"
        model_name: Model ID.
        
    Returns:
        Dictionary with explanation, language, complexity, and bugs identified.
    """
    try:
        prompt = (
            "Analyze the code snippet below. "
            "Return a JSON object containing:\n"
            "1. 'language': The detected programming language.\n"
            "2. 'explanation': A concise explanation of what the code does.\n"
            "3. 'bugs': A list of bugs, syntax issues, or potential runtime errors identified (empty list if clean).\n"
            "4. 'time_complexity': Time complexity analysis (e.g. O(n), O(log n)) with brief justification.\n\n"
            f"Code snippet:\n{code}"
        )
        
        class CodeSchema(llm.pydantic.BaseModel):
            language: str
            explanation: str
            bugs: list
            time_complexity: str
            
        res_text = llm.generate_text(
            prompt=prompt,
            system_instruction="You are an advanced programming assistant and static code analyzer.",
            json_schema=CodeSchema,
            suite=suite,
            model_name=model_name
        )
        
        result = json.loads(res_text)
        return {
            "language": result.get("language", "Unknown"),
            "explanation": result.get("explanation", ""),
            "bugs": result.get("bugs", []),
            "time_complexity": result.get("time_complexity", "Unknown")
        }
    except Exception as e:
        logger.error(f"Code explanation tool failed: {e}")
        raise ToolExecutionError(f"Code explanation failed: {str(e)}")
