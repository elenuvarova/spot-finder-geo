"""SpotFinder FastAPI backend.

Serves the precomputed Antwerpen GeoJSON and an AI zone-explainer with
graceful degradation. Does NO heavy computation. Designed for the Render
free tier (single web service, /health keep-alive pings).
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from explain import explain

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("spotfinder")

# Path relative to THIS module so it works regardless of the working directory.
GEOJSON_PATH = Path(__file__).parent / "data" / "antwerpen.geojson"

# In-memory cache for the GeoJSON (loaded once at startup via the lifespan).
_geojson_cache: bytes | None = None


def _load_geojson() -> None:
    """Load and cache the GeoJSON as raw bytes.

    Caching the bytes lets us serve it without re-parsing/re-serializing on
    every request. If the file is missing we leave the cache as None and the
    endpoint returns 503.
    """
    global _geojson_cache
    try:
        _geojson_cache = GEOJSON_PATH.read_bytes()
        logger.info("Loaded GeoJSON from %s (%d bytes)", GEOJSON_PATH, len(_geojson_cache))
    except FileNotFoundError:
        _geojson_cache = None
        logger.warning("GeoJSON not found at %s — /api/spots will return 503", GEOJSON_PATH)
    except OSError as exc:
        _geojson_cache = None
        logger.error("Failed to read GeoJSON at %s: %s", GEOJSON_PATH, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan handler: load and cache the GeoJSON at startup.

    Replaces the deprecated ``@app.on_event("startup")`` hook while preserving
    the exact behavior — the file is read once into ``_geojson_cache`` and a
    missing file leaves the cache as None so ``/api/spots`` returns a clear 503.
    """
    _load_geojson()
    yield


app = FastAPI(title="SpotFinder API", version="1.0.0", lifespan=lifespan)

# --- CORS -------------------------------------------------------------------
# Allowed origins from env FRONTEND_ORIGIN (comma-separated); default "*".
_frontend_origin = os.environ.get("FRONTEND_ORIGIN", "*").strip()
if _frontend_origin == "*" or not _frontend_origin:
    _allow_origins = ["*"]
else:
    _allow_origins = [o.strip() for o in _frontend_origin.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Request model (pydantic v2) -------------------------------------------
class ExplainRequest(BaseModel):
    type: Literal["cafe", "bakery", "confectionery"]
    vegan: bool = False
    props: dict = Field(default_factory=dict)


# --- Endpoints --------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    """Lightweight health check for Render keep-alive pings."""
    return {"status": "ok"}


@app.get("/api/spots")
def get_spots() -> Response:
    """Return the full Antwerpen GeoJSON FeatureCollection.

    Served from the in-memory cache as pre-serialized JSON bytes — we bypass
    FastAPI's serializer because the cached content is already valid JSON.
    Returns 503 with a clear message if the file was missing at startup.
    """
    if _geojson_cache is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "GeoJSON dataset is not available on the server. Expected file "
                f"at {GEOJSON_PATH.name} under the backend data directory."
            ),
        )
    return Response(content=_geojson_cache, media_type="application/json")


@app.post("/api/explain")
async def post_explain(req: ExplainRequest) -> dict:
    """Two-layer zone explainer.

    Tries the Gemini AI layer, falls back to the deterministic template on ANY
    failure. MUST NEVER return a 5xx — the orchestrator never raises, and we
    wrap defensively here as well.
    """
    try:
        return await explain(req.type, req.vegan, req.props)
    except Exception as exc:  # noqa: BLE001 - last-resort guard, never 5xx
        logger.error("Unexpected error in /api/explain, returning template: %s", exc)
        from explain import build_template_explanation

        return {
            "explanation": build_template_explanation(req.type, req.vegan, req.props),
            "source": "template",
        }


# --- Serve the built frontend (single-service deploy) -----------------------
# In the Docker image the built frontend is copied to ./static. When present,
# mount it at "/" so ONE Render service serves both the API and the UI from the
# same origin. Mounted AFTER the API routes above, so /health and /api/* always
# take precedence. Absent in local dev (Vite serves the frontend), where the API
# simply runs standalone.
_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="frontend")
    logger.info("Serving built frontend from %s", _static_dir)
