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
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /app/frontend/dist ./static
EXPOSE 8000
# Render injects $PORT; bind to it (fall back to 8000 locally).
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
