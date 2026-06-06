# Use a slim Python 3.11 base image
FROM python:3.11-slim

# Prevent python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Set workspace directory
WORKDIR /app

# Install system dependencies (including build utilities if required)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy configuration files
COPY pyproject.toml requirements.txt ./

# Install pip-tools or uv, then install dependencies
# We use standard pip installation from requirements.txt in Docker for maximum compatibility
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source folders
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Create uploads directory and set permissions
RUN mkdir -p /app/uploads && chmod 777 /app/uploads

# Expose server port
EXPOSE 8000

# Start server via Uvicorn (resolving dynamic port)
CMD uvicorn backend.main:app --host 0.0.0.0 --port $PORT
