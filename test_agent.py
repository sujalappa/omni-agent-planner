import os
import sys
import wave
import struct
import json
import logging
from pathlib import Path
from backend.agent import AgentOrchestrator
from backend import config

# Configure logging to console
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Helper to create a dummy WAV file for audio transcription testing
def create_dummy_wav(path: Path, duration_seconds: float = 3.0):
    sample_rate = 8000
    num_frames = int(sample_rate * duration_seconds)
    
    with wave.open(str(path), 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        # Write silent frames (zero bytes)
        for _ in range(num_frames):
            data = struct.pack('<h', 0)
            wav_file.writeframesraw(data)
    logger.info(f"Created dummy WAV file: {path} ({duration_seconds}s)")

# Helper to create a dummy PDF file with text inside
def create_dummy_pdf(path: Path, text: str):
    # Since pypdf is installed, we can write a basic empty PDF,
    # but to write raw text, creating a PDF programmatically in python without external libraries
    # like reportlab is tricky. We will write a minimal PDF structure containing the text string.
    pdf_content = (
        f"%PDF-1.4\n"
        f"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
        f"2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n"
        f"3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>> endobj\n"
        f"4 0 obj <</Length {len(text) + 40}>> stream\n"
        f"BT\n/F1 12 Tf\n70 700 Td\n({text}) Tj\nET\nendstream\nendobj\n"
        f"5 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj\n"
        f"xref\n0 6\n0000000000 65535 f\n"
        f"0000000009 00000 n\n"
        f"0000000056 00000 n\n"
        f"0000000111 00000 n\n"
        f"0000000212 00000 n\n"
        f"0000000305 00000 n\n"
        f"trailer <</Size 6 /Root 1 0 R>>\n"
        f"startxref\n386\n%%EOF"
    )
    with open(path, "wb") as f:
        f.write(pdf_content.encode('latin-1'))
    logger.info(f"Created dummy PDF file: {path}")

def run_test_case(title: str, query: str, file_infos: list):
    print("\n" + "="*80)
    print(f"TEST CASE: {title}")
    print(f"Query: {query}")
    print(f"Files: {[f['name'] for f in file_infos]}")
    print("="*80)
    
    if not config.GEMINI_API_KEY:
        print("SKIPPED: GEMINI_API_KEY is not configured in .env. Cannot call Gemini API.")
        return
        
    orchestrator = AgentOrchestrator()
    result = orchestrator.process_query(query, file_infos)
    
    print("\n[EXTRACTED CONTENT]")
    for item in result["extracted_content"]:
        ext_text = item.get("extracted_text", "")
        # Truncate output for logging
        preview = ext_text[:120] + "..." if len(ext_text) > 120 else ext_text
        print(f"- File '{item['name']}' ({item['type']}) parsed via {item.get('method')}: {preview}")
        
    print("\n[AGENT REASONING PLAN TRACE]")
    for node in result["trace"]:
        print(f"Step {node['step']} [{node['type'].upper()}]: {node['reasoning']}")
        if node.get("details"):
            print(f"  Details: {json.dumps(node['details'])}")
            
    print("\n[FINAL TEXT OUTPUT]")
    print(result["output"])
    
    print("\n[COST ESTIMATION]")
    print(json.dumps(result["cost"], indent=2))
    print("="*80 + "\n")


if __name__ == "__main__":
    # Create temp directory for test assets
    temp_dir = Path("./temp_test_assets")
    temp_dir.mkdir(exist_ok=True)
    
    # 1. Setup mock assets
    audio_path = temp_dir / "test_lecture.wav"
    pdf_path = temp_dir / "meeting_notes.pdf"
    yt_pdf_path = temp_dir / "youtube_links.pdf"
    
    create_dummy_wav(audio_path, duration_seconds=5.0)
    create_dummy_pdf(pdf_path, "Action items from marketing: 1. Sujal to deploy server by Tuesday. 2. Design the logo. 3. Finalize budget.")
    create_dummy_pdf(yt_pdf_path, "Watch our project tutorial here: https://www.youtube.com/watch?v=dQw4w9WgXcQ for insights.")
    
    # Test case files dictionary configuration
    files_tc1 = [{"name": "test_lecture.wav", "path": str(audio_path), "type": "audio"}]
    files_tc2 = [{"name": "meeting_notes.pdf", "path": str(pdf_path), "type": "pdf"}]
    files_tc4 = [{"name": "youtube_links.pdf", "path": str(yt_pdf_path), "type": "pdf"}]
    files_tc5 = [
        {"name": "meeting_notes.pdf", "path": str(pdf_path), "type": "pdf"},
        {"name": "test_lecture.wav", "path": str(audio_path), "type": "audio"}
    ]
    
    try:
        # Check command argument or run all
        test_to_run = sys.argv[1] if len(sys.argv) > 1 else "all"
        
        if test_to_run in ["1", "all"]:
            # Test Case 1 — Audio Transcription + Summary
            run_test_case(
                "Test Case 1 — Audio Transcription + Summary",
                "Summarize this audio file and give me the duration.",
                files_tc1
            )
            
        if test_to_run in ["2", "all"]:
            # Test Case 2 — PDF + Natural Language Query
            run_test_case(
                "Test Case 2 — PDF + Natural Language Query",
                "What are the action items?",
                files_tc2
            )
            
        if test_to_run in ["3", "all"]:
            # Test Case 3 — Image with Code
            # We can write an image for testing, but since OCR is better tested with a real visual
            # file, we instruct the user how to test it or skip.
            print("Note: Test Case 3 requires a screenshot containing code. Please test manually via web UI.")
            
        if test_to_run in ["4", "all"]:
            # Test Case 4 — Cross-Input Multi-Tool Chain
            run_test_case(
                "Test Case 4 — Cross-Input Multi-Tool Chain",
                "Hit the YT URL in this PDF and give me a summary of it",
                files_tc4
            )
            
        if test_to_run in ["5", "all"]:
            # Test Case 5 — Multi-File Unified Query
            run_test_case(
                "Test Case 5 — Multi-File Unified Query",
                "Do the audio and the document discuss the same topic?",
                files_tc5
            )
            
    except KeyboardInterrupt:
        logger.info("Tests canceled by user.")
    finally:
        # Clean up mock files
        for f in [audio_path, pdf_path, yt_pdf_path]:
            if f.exists():
                f.unlink()
        if temp_dir.exists():
            temp_dir.rmdir()
        logger.info("Cleaned up temporary test assets.")
