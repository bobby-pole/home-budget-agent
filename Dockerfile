# Dockerfile

# --- STAGE 1: Build Frontend (React + Vite) ---
FROM node:20-alpine as build-frontend

WORKDIR /app
# Copy frontend dependencies
COPY frontend/package*.json ./
RUN npm ci

# Copy frontend source code
COPY frontend/ ./
# Build the application (output will go to /app/dist)
RUN npm run build

# --- STAGE 2: Build Backend & Serve (Python) ---
FROM python:3.11-slim as production

WORKDIR /app

# Install system dependencies (only necessary ones)
# curl may be needed for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy backend dependencies
COPY backend/requirements.txt ./
# --no-cache-dir drastycznie zmniejsza rozmiar obrazu
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY backend/ ./

# Copy the built frontend from Stage 1 to the static folder in the backend
# Vite builds to 'dist' by default, we'll put it in 'static' in the container
COPY --from=build-frontend /app/dist /app/static

# Environment variables for Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Open port
EXPOSE 8000

# Run the server (host 0.0.0.0 is required in Docker)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]