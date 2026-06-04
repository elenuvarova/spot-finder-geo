# SpotFinder — single service: build the frontend, then serve API + UI from FastAPI.
# Stage 1 — build the React/Vite frontend. No VITE_API_URL is set, so api.js uses
# its relative same-origin default ('') and the built app calls /api/* on its own host.
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2 — Python backend that also serves the built frontend.
FROM python:3.12-slim
WORKDIR /app/backend

# Install deps first for layer caching.
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code + the built frontend (served by FastAPI at "/").
COPY backend/ ./
COPY --from=frontend /app/frontend/dist ./static

# Run as a non-root user. Create it after copying so we can hand over ownership,
# then drop privileges — the process never runs as root in the container.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Healthcheck: probe FastAPI's /health on the port the app binds. curl is NOT in
# python:3.12-slim, so use the stdlib (python3) — same convention as the other
# single-container apps. Coolify/Traefik and Render both read this.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python3 -c "import os,urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health', timeout=4).status==200 else 1)"

# Coolify/Traefik route to the exposed port (default 8000). Render injects $PORT;
# bind to it when present, otherwise 8000. host 0.0.0.0 so the platform can reach it.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
