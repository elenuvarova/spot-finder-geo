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

DATA_DIR = Path(__file__).parent / "data"

# Cities we serve. `slug` must match backend/data/<slug>.geojson and the
# pipeline's CITIES keys. `center`/`zoom` drive the frontend map view.
CITIES = [
    {"slug": "antwerpen", "name": "Antwerp", "center": [4.40, 51.21], "zoom": 12},
    {"slug": "leuven", "name": "Leuven", "center": [4.70, 50.879], "zoom": 13},
]
DEFAULT_CITY = "antwerpen"

# In-memory cache: slug -> pre-serialized GeoJSON bytes (loaded at startup).
_geojson_cache: dict[str, bytes] = {}


def _load_geojson() -> None:
    """Load and cache each city's GeoJSON as raw bytes.

    Caching the bytes lets us serve them without re-parsing on every request. A
    city whose file is missing is simply skipped (omitted from /api/cities, 503
    on /api/spots), so the service still boots with whatever data is present.
    """
    _geojson_cache.clear()
    for c in CITIES:
        path = DATA_DIR / f"{c['slug']}.geojson"
        try:
            _geojson_cache[c["slug"]] = path.read_bytes()
            logger.info("Loaded GeoJSON for %s (%d bytes)", c["slug"], len(_geojson_cache[c["slug"]]))
        except (FileNotFoundError, OSError):
            logger.warning("GeoJSON for %s not found at %s — skipping", c["slug"], path)


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


@app.get("/api/cities")
def get_cities() -> dict:
    """List cities that have data loaded, with their map view (center/zoom)."""
    available = [c for c in CITIES if c["slug"] in _geojson_cache]
    default = DEFAULT_CITY if DEFAULT_CITY in _geojson_cache else (
        available[0]["slug"] if available else None)
    return {"cities": available, "default": default}


@app.get("/api/spots")
def get_spots(city: str = DEFAULT_CITY) -> Response:
    """Return a city's GeoJSON FeatureCollection (default: Antwerp).

    Served from the in-memory cache as pre-serialized JSON bytes — we bypass
    FastAPI's serializer because the cached content is already valid JSON.
    Returns 503 if that city's file was missing/unloaded at startup.
    """
    data = _geojson_cache.get(city)
    if data is None:
        raise HTTPException(
            status_code=503,
            detail=f"GeoJSON for city '{city}' is not available on the server.",
        )
    return Response(content=data, media_type="application/json")


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
