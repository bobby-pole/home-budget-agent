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

# --- STAGE 2: Backend Base (Python dependencies & Security) ---
FROM python:3.11-slim as backend-base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --gid 1001 appuser

# Copy backend dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY backend/ ./

# Change ownership to non-root user
RUN chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/home/appuser/.local/bin:$PATH"

# Open port
EXPOSE 8000

# Default command (can be overridden)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --- STAGE 3: Production (Combine Frontend & Backend) ---
FROM backend-base as production

# Switch to root temporarily to copy files
USER root

# Copy the built frontend from Stage 1
COPY --from=build-frontend --chown=appuser:appgroup /app/dist /app/static

# Switch back to non-root user
USER appuser