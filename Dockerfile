# Production image for the Macro RAG backend (also serves the static frontend).
# The app serves ../frontend relative to the backend working dir, so the
# backend/ + frontend/ sibling layout is preserved inside the image.
FROM python:3.12-slim

# Faster, quieter Python in containers
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (layer cached until pyproject changes)
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app/__init__.py backend/app/__init__.py
RUN pip install -e ./backend

# Copy the rest of the source
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Run from backend/ so `../frontend` and Alembic resolve correctly
WORKDIR /app/backend
RUN chmod +x docker-entrypoint.sh

# Entrypoint runs migrations then exec's uvicorn as PID 1 (clean SIGTERM).
CMD ["./docker-entrypoint.sh"]
