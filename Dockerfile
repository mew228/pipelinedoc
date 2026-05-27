# Stage 1: Python backend
FROM python:3.12-slim

# Install Node.js + npm (required so the backend can spawn npx @gitlab-org/gitlab-mcp-server)
RUN apt-get update && \
    apt-get install -y --no-install-recommends nodejs npm && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache friendly)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ .

# Hugging Face Spaces expects 7860 by default
EXPOSE 7860

# Pre-warm npx cache so first request doesn't pay cold-start install cost
RUN npx -y gitlab-mcp --help || true

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
