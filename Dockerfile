# ---------------------------------------------------------------------------
# Lumen — single image, single port.
#
# Stage 1 builds the UI; stage 2 runs the API and serves that build from the
# same origin, so `docker compose up` publishes one port and needs no proxy.
# ---------------------------------------------------------------------------

# --- stage 1: build the UI -------------------------------------------------
FROM node:22-slim AS ui

WORKDIR /ui
# Copy manifests first so npm's layer is cached until dependencies change.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

COPY frontend/ ./
RUN npm run build


# --- stage 2: runtime ------------------------------------------------------
FROM python:3.11-slim AS runtime

# tesseract-ocr enables the OCR capability (scanned PDFs, photographed notes).
# Everything else the app needs is a Python wheel.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    FRONTEND_DIST=/app/frontend/dist

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r backend/requirements.txt \
    && pip install pytesseract==0.3.13

COPY backend/ ./backend/
COPY --from=ui /ui/dist ./frontend/dist

# Run unprivileged; /data holds uploads, the database and generated artifacts.
RUN useradd --create-home --uid 10001 lumen \
    && mkdir -p /data \
    && chown -R lumen:lumen /data /app
USER lumen

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
