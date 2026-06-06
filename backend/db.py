import logging
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from supabase import create_client, Client

from backend import config

# Configure logging
logger = logging.getLogger(__name__)

# Initialize client
supabase_client: Optional[Client] = None

if config.SUPABASE_URL and config.SUPABASE_KEY:
    try:
        supabase_client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
        logger.info("Supabase client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
else:
    logger.info("Supabase credentials not fully configured. Operating in local fallback mode.")


def upload_file_to_supabase(file_path: Path, filename: str, mime_type: str) -> Optional[str]:
    """
    Uploads a file to Supabase Storage and returns its public URL.
    
    Args:
        file_path: Path to the local file.
        filename: Name of the file.
        mime_type: File content MIME type.
        
    Returns:
        The public access URL or None if upload fails.
    """
    if not supabase_client:
        logger.info("Supabase is disabled. Skipping storage upload.")
        return None

    try:
        # Generate a unique path inside the bucket to prevent collisions
        unique_name = f"{uuid.uuid4()}_{filename}"
        
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        logger.info(f"Uploading {filename} to Supabase bucket '{config.SUPABASE_BUCKET}'...")
        
        # Perform upload
        supabase_client.storage.from_(config.SUPABASE_BUCKET).upload(
            path=unique_name,
            file=file_bytes,
            file_options={"content-type": mime_type}
        )
        
        # Retrieve public URL
        url_response = supabase_client.storage.from_(config.SUPABASE_BUCKET).get_public_url(unique_name)
        
        public_url = None
        if isinstance(url_response, str):
            public_url = url_response
        elif hasattr(url_response, "public_url"):
            public_url = url_response.public_url
        else:
            public_url = str(url_response)

        logger.info(f"File uploaded successfully. Public URL: {public_url}")
        return public_url

    except Exception as e:
        logger.error(f"Supabase file upload failed for {filename}: {e}", exc_info=True)
        return None


def save_session(
    query: str,
    output: str,
    extracted_content: List[Dict[str, Any]],
    cost_data: Dict[str, Any]
) -> Optional[str]:
    """
    Saves the query, synthesized output, extracted contents for different types,
    and cost details to the PostgreSQL 'sessions' table.
    
    Args:
        query: User text prompt.
        output: Synthesized text response.
        extracted_content: List of processed files with extracted text.
        cost_data: Cost estimation stats.
        
    Returns:
        The database session entry UUID (str) or None.
    """
    if not supabase_client:
        logger.info("Supabase is disabled. Skipping database session logging.")
        return None

    try:
        # Aggregators for different file inputs
        pdf_texts = []
        image_texts = []
        audio_texts = []
        
        has_pdf = False
        has_image = False
        has_audio = False
        
        for item in extracted_content:
            file_type = item.get("type", "")
            text = item.get("extracted_text", "")
            
            if not text:
                continue
                
            if file_type == "pdf":
                pdf_texts.append(text)
                has_pdf = True
            elif file_type in ["image", "png", "jpg", "jpeg"]:
                image_texts.append(text)
                has_image = True
            elif file_type in ["audio", "mp3", "wav", "m4a"]:
                audio_texts.append(text)
                has_audio = True

        session_data = {
            "text_query": query,
            "output": output,
            
            # Structured columns for different inputs
            "extracted_pdf_text": "\n\n".join(pdf_texts) if pdf_texts else None,
            "extracted_image_text": "\n\n".join(image_texts) if image_texts else None,
            "extracted_audio_text": "\n\n".join(audio_texts) if audio_texts else None,
            
            # Status flags
            "has_pdf": has_pdf,
            "has_image": has_image,
            "has_audio": has_audio,
            
            # Cost and performance logs
            "input_tokens": cost_data.get("input_tokens", 0),
            "output_tokens": cost_data.get("output_tokens", 0),
            "audio_seconds": cost_data.get("audio_seconds", 0.0),
            "estimated_cost_usd": cost_data.get("estimated_cost_usd", 0.0)
        }

        logger.info("Inserting session record into Supabase PostgreSQL...")
        response = supabase_client.table("sessions").insert(session_data).execute()
        
        if response.data and len(response.data) > 0:
            session_id = response.data[0]["id"]
            logger.info(f"Session saved successfully with ID: {session_id}")
            return session_id
            
        return None
    except Exception as e:
        logger.error(f"Failed to save session to Supabase: {e}", exc_info=True)
        return None


def save_traces(session_id: str, trace_list: List[Dict[str, Any]]):
    """
    Saves the chronological agent reasoning trace steps linked to the session.
    
    Args:
        session_id: The parent session UUID.
        trace_list: List of planned steps.
    """
    if not supabase_client or not session_id:
        return

    try:
        trace_records = []
        for node in trace_list:
            trace_records.append({
                "session_id": session_id,
                "step_index": node.get("step", 0),
                "type": node.get("type", "finish"),
                "reasoning": node.get("reasoning", ""),
                "details": node.get("details")  # handles JSON serialization automatically
            })

        if trace_records:
            logger.info(f"Saving {len(trace_records)} plan traces linked to session {session_id}...")
            supabase_client.table("traces").insert(trace_records).execute()
            
    except Exception as e:
        logger.error(f"Failed to save traces to Supabase: {e}", exc_info=True)


def save_file_uploads(session_id: str, file_mappings: List[Dict[str, Any]]):
    """
    Saves uploaded file details and their public Supabase Storage links.
    
    Args:
        session_id: The parent session UUID.
        file_mappings: List of dicts with 'name', 'type', and 'public_url'.
    """
    if not supabase_client or not session_id:
        return

    try:
        upload_records = []
        for item in file_mappings:
            if not item.get("public_url"):
                continue
                
            upload_records.append({
                "session_id": session_id,
                "filename": item.get("name"),
                "file_type": item.get("type"),
                "public_url": item.get("public_url")
            })

        if upload_records:
            logger.info(f"Saving {len(upload_records)} file mappings to session {session_id}...")
            supabase_client.table("file_uploads").insert(upload_records).execute()
            
    except Exception as e:
        logger.error(f"Failed to save file uploads mapping to Supabase: {e}", exc_info=True)
