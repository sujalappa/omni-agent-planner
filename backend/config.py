import os
from pathlib import Path
from dotenv import load_dotenv

# Load local environment variables if present
load_dotenv()

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "frontend"

# Ensure runtime directories exist
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Configuration values
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"
PORT = int(os.getenv("PORT", 8000))
HOST = "0.0.0.0"

# Groq and Hugging Face API Credentials (Optional - set here or in environment)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "your-groq-key")
HF_API_TOKEN = os.getenv("HF_API_TOKEN", "your-huggingface-token")

# Supabase Settings (Hardcoded placeholders - replace with your project values if using Supabase)
SUPABASE_URL = "https://tfmepdhcdoftaceywxso.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRmbWVwZGhjZG9mdGFjZXl3eHNvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA2NDAzOTQsImV4cCI6MjA5NjIxNjM5NH0.msify09OpRms2NjgTujYG2ltU89oFDSqzVb9b0Z5ac0"
SUPABASE_BUCKET = "agent-uploads"

# Security check
if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY is not set in the environment variables.")
if SUPABASE_URL == "https://your-supabase-project.supabase.co" or not SUPABASE_KEY:
    print("WARNING: Supabase variables are left as placeholders. Operating in local-only mode.")
