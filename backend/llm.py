import os
import json
import base64
import logging
import requests
from pathlib import Path
from typing import Dict, Any, List, Optional
import google.generativeai as genai

from backend import config
import pydantic


logger = logging.getLogger(__name__)

class LLMGatewayError(Exception):
    """Raised when an API call in the LLM Gateway fails."""
    pass


def generate_text(
    prompt: str,
    system_instruction: Optional[str] = None,
    json_schema: Optional[Any] = None,
    suite: str = "proprietary",
    model_name: str = "gemini-2.5-flash"
) -> str:
    """
    Generates text or structured JSON from the selected LLM provider.
    
    Args:
        prompt: User prompt content.
        system_instruction: Optional system rules.
        json_schema: Optional Pydantic schema class for forcing JSON.
        suite: "proprietary" or "opensource"
        model_name: Specific model string (e.g. gemini-2.5-flash, llama-3.3-70b-versatile).
        
    Returns:
        The text string returned by the provider.
    """
    if suite == "opensource" or model_name == "llama-3.3-70b-versatile":
        return _generate_groq_text(prompt, system_instruction, json_schema)
    else:
        # Default fallback to Google Gemini
        return _generate_gemini_text(prompt, system_instruction, json_schema, model_name)


def ocr_image(file_path: Path, suite: str = "proprietary", model_name: str = "gemini-2.5-flash") -> Dict[str, Any]:
    """
    Performs OCR on an image file.
    - Proprietary: Uses Gemini Vision API.
    - OpenSource: Uses meta-llama/Llama-3.2-11B-Vision-Instruct via Hugging Face.
    """
    if suite == "opensource":
        return _ocr_huggingface_image(file_path)
    else:
        return _ocr_gemini_image(file_path, model_name)


def transcribe_audio(file_path: Path, suite: str = "proprietary", model_name: str = "gemini-2.5-flash") -> Dict[str, Any]:
    """
    Transcribes audio files.
    - Proprietary: Uses Gemini Audio API.
    - OpenSource: Uses Whisper-large-v3 via Groq.
    """
    if suite == "opensource":
        return _transcribe_groq_audio(file_path)
    else:
        return _transcribe_gemini_audio(file_path, model_name)


# ==============================================================================
# Google Gemini Private Helpers
# ==============================================================================

def _get_gemini_schema(annotation: Any) -> Dict[str, Any]:
    import typing
    from typing import get_origin, get_args, Union, List, Dict, Any
    import pydantic

    origin = get_origin(annotation)
    args = get_args(annotation)
    
    if origin is Union:
        non_none_args = [a for a in args if a is not type(None)]
        is_nullable = len(non_none_args) < len(args)
        if len(non_none_args) == 1:
            schema = _get_gemini_schema(non_none_args[0])
            if is_nullable:
                schema["nullable"] = True
            return schema
        else:
            return {"type": "STRING", "nullable": is_nullable}

    if origin in (list, List, typing.Sequence, typing.Iterable):
        item_type = args[0] if args else Any
        return {
            "type": "ARRAY",
            "items": _get_gemini_schema(item_type)
        }

    if origin in (dict, Dict):
        return {
            "type": "OBJECT"
        }

    if isinstance(annotation, type) and issubclass(annotation, pydantic.BaseModel):
        properties = {}
        required = []
        for field_name, field in annotation.model_fields.items():
            field_schema = _get_gemini_schema(field.annotation)
            if field.is_required():
                required.append(field_name)
            properties[field_name] = field_schema
            
        schema = {
            "type": "OBJECT",
            "properties": properties
        }
        if required:
            schema["required"] = required
        return schema

    if annotation is str:
        return {"type": "STRING"}
    elif annotation is int:
        return {"type": "INTEGER"}
    elif annotation is float:
        return {"type": "NUMBER"}
    elif annotation is bool:
        return {"type": "BOOLEAN"}
    elif annotation is Any:
        return {"type": "STRING"}
        
    return {"type": "STRING"}


def _generate_gemini_text(prompt: str, system_instruction: Optional[str], json_schema: Optional[Any], model_name: str) -> str:
    if not config.GEMINI_API_KEY:
        raise LLMGatewayError("GEMINI_API_KEY is not set in backend configurations.")
    
    try:
        genai.configure(api_key=config.GEMINI_API_KEY)
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_instruction
        )
        
        gen_config = {}
        if json_schema:
            # Generate clean, flat schema to bypass google-generativeai Pydantic schema bug
            clean_schema = _get_gemini_schema(json_schema)
            gen_config = {
                "response_mime_type": "application/json",
                "response_schema": clean_schema
            }
            
        response = model.generate_content(prompt, generation_config=gen_config)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini text generation failed: {e}")
        raise LLMGatewayError(f"Gemini API Error: {str(e)}")


def _ocr_gemini_image(file_path: Path, model_name: str) -> Dict[str, Any]:
    if not config.GEMINI_API_KEY:
        raise LLMGatewayError("GEMINI_API_KEY is not set in backend configurations.")
        
    try:
        genai.configure(api_key=config.GEMINI_API_KEY)
        model = genai.GenerativeModel(model_name)
        
        with open(file_path, "rb") as img_file:
            img_bytes = img_file.read()
            
        suffix = file_path.suffix.lower().replace(".", "")
        mime_type = f"image/{suffix}" if suffix in ["png", "jpeg", "jpg", "webp"] else "image/png"
        
        image_part = {"mime_type": mime_type, "data": img_bytes}
        prompt = (
            "Analyze this image and perform OCR to extract all text. "
            "Return a JSON object containing:\n"
            "1. 'transcript': The complete extracted text.\n"
            "2. 'confidence': A float between 0.0 and 1.0 reflecting your confidence in the OCR accuracy."
        )
        
        response = model.generate_content(
            [image_part, prompt],
            generation_config={"response_mime_type": "application/json"}
        )
        result = json.loads(response.text)
        return {
            "text": result.get("transcript", ""),
            "confidence": float(result.get("confidence", 0.90)),
            "method": "gemini_vision_ocr"
        }
    except Exception as e:
        logger.error(f"Gemini OCR failed: {e}")
        raise LLMGatewayError(f"Gemini OCR failed: {str(e)}")


def _transcribe_gemini_audio(file_path: Path, model_name: str) -> Dict[str, Any]:
    if not config.GEMINI_API_KEY:
        raise LLMGatewayError("GEMINI_API_KEY is not set.")
        
    try:
        uploaded_file = genai.upload_file(str(file_path))
        model = genai.GenerativeModel(model_name)
        prompt = (
            "Transcribe the following audio recording. Convert speech to clear, "
            "formatted text. Filter out stutters or filler words ('um', 'uh', etc.) "
            "and apply clean grammatical structure. Return the transcribed text only."
        )
        response = model.generate_content([uploaded_file, prompt])
        uploaded_file.delete()
        
        return {
            "text": response.text.strip(),
            "method": "gemini_audio_transcription"
        }
    except Exception as e:
        logger.error(f"Gemini Audio Transcription failed: {e}")
        raise LLMGatewayError(f"Gemini Audio Transcription failed: {str(e)}")


# ==============================================================================
# Groq Private Helpers (Open Source Suite Text & Audio)
# ==============================================================================

def _generate_groq_text(prompt: str, system_instruction: Optional[str], json_schema: Optional[Any]) -> str:
    if not config.GROQ_API_KEY or config.GROQ_API_KEY == "your-groq-key":
        raise LLMGatewayError("GROQ_API_KEY is not set in configurations.")
        
    try:
        # If schema is present, inject it into the prompt to guide Groq and satisfy its JSON validator
        if json_schema:
            schema_dict = json_schema.model_json_schema()
            prompt += (
                f"\n\nYou MUST return your response as a valid JSON object. "
                f"The response must strictly match the following JSON schema:\n"
                f"{json.dumps(schema_dict, indent=2)}\n\n"
                f"Ensure the JSON output is valid, contains the exact keys, and complies with the schema. Output JSON only."
            )
            # Ensure the system instruction contains the word "json" to satisfy Groq JSON mode requirement
            if system_instruction:
                system_instruction += " You MUST return your response as a valid JSON object."
            else:
                system_instruction = "You are a helpful assistant. You MUST return your response as a valid JSON object."

        headers = {
            "Authorization": f"Bearer {config.GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": messages,
            "temperature": 0.2
        }
        
        if json_schema:
            payload["response_format"] = {"type": "json_object"}
            
        response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
        
        # Check status and extract details on failure
        if response.status_code != 200:
            try:
                err_data = response.json()
                err_msg = err_data.get("error", {}).get("message", response.text)
            except Exception:
                err_msg = response.text
            logger.error(f"Groq API returned status {response.status_code}: {err_msg}")
            raise LLMGatewayError(f"Groq API Error ({response.status_code}): {err_msg}")
            
        return response.json()["choices"][0]["message"]["content"]
    except LLMGatewayError:
        raise
    except Exception as e:
        logger.error(f"Groq text generation failed: {e}")
        raise LLMGatewayError(f"Groq API Error: {str(e)}")


def _transcribe_groq_audio(file_path: Path) -> Dict[str, Any]:
    if not config.GROQ_API_KEY or config.GROQ_API_KEY == "your-groq-key":
        raise LLMGatewayError("GROQ_API_KEY is not set in configurations.")
        
    try:
        headers = {
            "Authorization": f"Bearer {config.GROQ_API_KEY}"
        }
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "audio/octet-stream")}
            data = {"model": "whisper-large-v3", "response_format": "json"}
            
            response = requests.post("https://api.groq.com/openai/v1/audio/transcriptions", headers=headers, files=files, data=data)
            response.raise_for_status()
            
        return {
            "text": response.json().get("text", "").strip(),
            "method": "groq_whisper_transcription"
        }
    except Exception as e:
        logger.error(f"Groq Whisper audio transcription failed: {e}")
        raise LLMGatewayError(f"Groq STT failed: {str(e)}")


# ==============================================================================
# Hugging Face Private Helpers (Open Source Suite OCR)
# ==============================================================================

def _ocr_huggingface_image(file_path: Path) -> Dict[str, Any]:
    if not config.HF_API_TOKEN or config.HF_API_TOKEN == "your-huggingface-token":
        raise LLMGatewayError("HF_API_TOKEN is not set in configurations.")
        
    try:
        with open(file_path, "rb") as img_file:
            img_base64 = base64.b64encode(img_file.read()).decode("utf-8")
            
        suffix = file_path.suffix.lower().replace(".", "")
        mime_type = f"image/{suffix}" if suffix in ["png", "jpeg", "jpg", "webp"] else "image/png"
        
        headers = {
            "Authorization": f"Bearer {config.HF_API_TOKEN}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "CohereLabs/aya-vision-32b",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Analyze this image and perform OCR. Extract all text content verbatim. "
                                    "Return a JSON object containing:\n"
                                    "1. 'transcript': The extracted text content.\n"
                                    "2. 'confidence': A float between 0.0 and 1.0 reflecting your confidence in the OCR accuracy. "
                                    "Output valid JSON only."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                    "url": f"data:{mime_type};base64,{img_base64}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 1024
        }
        
        logger.info("Sending OCR request to Hugging Face CohereLabs/aya-vision-32b via router...")
        response = requests.post(
            "https://router.huggingface.co/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=45
        )
        
        if response.status_code != 200:
            try:
                err_data = response.json()
                err_msg = err_data.get("error", {}).get("message", response.text)
            except Exception:
                err_msg = response.text
            raise LLMGatewayError(f"Hugging Face API Error ({response.status_code}): {err_msg}")
            
        content = response.json()["choices"][0]["message"]["content"].strip()
        
        # Try parsing content as JSON first
        try:
            # Clean potential markdown block formatting from JSON string
            cleaned_content = content
            if cleaned_content.startswith("```json"):
                cleaned_content = cleaned_content[7:]
            elif cleaned_content.startswith("```"):
                cleaned_content = cleaned_content[3:]
            if cleaned_content.endswith("```"):
                cleaned_content = cleaned_content[:-3]
            cleaned_content = cleaned_content.strip()
            
            result = json.loads(cleaned_content)
            extracted_text = result.get("transcript", "")
            confidence = float(result.get("confidence", 0.85))
        except Exception:
            logger.info("Hugging Face OCR response is not valid JSON. Falling back to treating content as plain text.")
            extracted_text = content
            confidence = 0.85
            
        return {
            "text": extracted_text,
            "confidence": confidence,
            "method": "huggingface_aya_vision_ocr"
        }
    except Exception as e:
        logger.error(f"Hugging Face OCR failed: {e}", exc_info=True)
        raise LLMGatewayError(f"Hugging Face OCR failed: {str(e)}")
