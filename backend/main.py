import os
import shutil
import logging
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import config
from backend.agent import AgentOrchestrator

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Data Smith AI - Multi-Input Agent",
    description="FastAPI backend for multi-input agentic task planner and executor.",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helper to determine file type based on file extension
def classify_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    elif ext in [".png", ".jpg", ".jpeg", ".webp"]:
        return "image"
    elif ext in [".mp3", ".wav", ".m4a", ".ogg", ".flac"]:
        return "audio"
    else:
        return "unknown"

# Route for query processing and tool execution
@app.post("/api/process")
async def process_inputs(
    query: Optional[str] = Form(None),
    history: Optional[str] = Form(None),
    suite: Optional[str] = Form("proprietary"),
    model: Optional[str] = Form("gemini-2.5-flash"),
    files: List[UploadFile] = File(default=[])
):
    # If no query is provided, default to an empty string (the agent will trigger the clarifying question flow)
    user_query = query.strip() if query else ""
    active_suite = suite.strip() if suite else "proprietary"
    active_model = model.strip() if model else "gemini-2.5-flash"
    
    saved_files = []
    
    try:
        # Save files locally
        for upload_file in files:
            if not upload_file.filename:
                continue
                
            safe_filename = Path(upload_file.filename).name
            file_path = config.UPLOAD_DIR / safe_filename
            
            # Save file stream
            with file_path.open("wb") as buffer:
                shutil.copyfileobj(upload_file.file, buffer)
                
            file_type = classify_file_type(safe_filename)
            saved_files.append({
                "name": safe_filename,
                "path": str(file_path),
                "type": file_type
            })
            logger.info(f"Saved file {safe_filename} to {file_path}")
            
        # Orchestrate processing
        orchestrator = AgentOrchestrator()
        import json
        history_list = json.loads(history) if history else []
        result = orchestrator.process_query(user_query, saved_files, active_suite, active_model, history_list)
        
        # Integrate Supabase Persistence Layer
        from backend import db
        
        file_mappings = []
        for file_info in saved_files:
            file_path = Path(file_info["path"])
            filename = file_info["name"]
            file_type = file_info["type"]
            
            # Formulate MIME types
            mime_type = "application/octet-stream"
            if file_type == "pdf":
                mime_type = "application/pdf"
            elif file_type == "image":
                mime_type = f"image/{file_path.suffix.lower().replace('.', '')}"
            elif file_type == "audio":
                mime_type = f"audio/{file_path.suffix.lower().replace('.', '')}"
            
            public_url = db.upload_file_to_supabase(file_path, filename, mime_type)
            if public_url:
                file_mappings.append({
                    "name": filename,
                    "type": file_type,
                    "public_url": public_url
                })
        
        # Save session history, files mappings, and planning steps to PostgreSQL
        if file_mappings or user_query:
            # Map public URLs to extracted content list
            for content in result.get("extracted_content", []):
                for fm in file_mappings:
                    if content["name"] == fm["name"]:
                        content["public_url"] = fm["public_url"]
                        break
            
            session_id = db.save_session(
                query=user_query,
                output=result.get("output", ""),
                extracted_content=result.get("extracted_content", []),
                cost_data=result.get("cost", {})
            )
            
            if session_id:
                db.save_traces(session_id, result.get("trace", []))
                db.save_file_uploads(session_id, file_mappings)
                result["db_session_id"] = session_id
                
        return result
        
    except Exception as e:
        logger.error(f"Error processing API request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
        
    finally:
        # Cleanup saved files to prevent disk bloating
        for file_info in saved_files:
            file_path = Path(file_info["path"])
            if file_path.exists():
                try:
                    file_path.unlink()
                    logger.info(f"Cleaned up file: {file_path}")
                except Exception as cleanup_err:
                    logger.warning(f"Failed to delete {file_path}: {cleanup_err}")

# Route for pre-execution cost estimation
@app.post("/api/cost")
async def estimate_cost(
    query: Optional[str] = Form(None),
    history: Optional[str] = Form(None),
    suite: Optional[str] = Form("proprietary"),
    model: Optional[str] = Form("gemini-2.5-flash"),
    files: List[UploadFile] = File(default=[])
):
    user_query = query.strip() if query else ""
    active_suite = suite.strip() if suite else "proprietary"
    active_model = model.strip() if model else "gemini-2.5-flash"
    saved_files = []
    
    try:
        # Save files temporarily for metadata duration checks
        for upload_file in files:
            if not upload_file.filename:
                continue
            safe_filename = Path(upload_file.filename).name
            file_path = config.UPLOAD_DIR / safe_filename
            
            with file_path.open("wb") as buffer:
                shutil.copyfileobj(upload_file.file, buffer)
                
            file_type = classify_file_type(safe_filename)
            saved_files.append({
                "name": safe_filename,
                "path": str(file_path),
                "type": file_type
            })
            
        orchestrator = AgentOrchestrator()
        import json
        history_list = json.loads(history) if history else []
        cost_estimation = orchestrator.estimate_plan_cost(user_query, saved_files, active_suite, active_model, history_list)
        return cost_estimation
        
    except Exception as e:
        logger.error(f"Error estimating cost: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
    finally:
        # Cleanup saved files
        for file_info in saved_files:
            file_path = Path(file_info["path"])
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception:
                    pass

# Mount static frontend pages
# The HTML/CSS/JS frontend files will be inside the /frontend directory.
# If index.html doesn't exist yet, we will create it.
if config.STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # Start the FastAPI server using uvicorn
    uvicorn.run("backend.main:app", host=config.HOST, port=config.PORT, reload=True)
