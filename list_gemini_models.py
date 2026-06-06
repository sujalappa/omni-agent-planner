import os
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("ERROR: GEMINI_API_KEY is not set in the environment or .env file.")
    print("Please set your API key and try again.")
    exit(1)

# Configure the API key
genai.configure(api_key=api_key)

print("Fetching available Gemini models from Google API...")
try:
    models = genai.list_models()
    print("\nAvailable Models for your API Key:")
    print("-" * 50)
    for model in models:
        # print supported methods (e.g. generateContent) and the short name
        methods = ", ".join(model.supported_generation_methods)
        if "generateContent" in model.supported_generation_methods:
            print(f"- Short Name: {model.name.replace('models/', '')}")
            print(f"  Full Name:  {model.name}")
            print(f"  Description: {model.description}")
            print("-" * 50)
except Exception as e:
    print(f"Failed to fetch models: {e}")
    print("Check if your GEMINI_API_KEY is correct and active.")
