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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from explain import explain

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("spotfinder")

DATA_DIR = Path(__file__).parent / "data"

# Cap on the /api/explain request body. The handler only reads a fixed set of
# small numeric props, so anything larger is abuse — reject before parsing.
MAX_EXPLAIN_BODY_BYTES = 8 * 1024  # ~8 KB

# IP-based rate limiter for the billable Gemini-backed /api/explain endpoint.
# On exceed we degrade to the deterministic template (HTTP 200) rather than
# returning a 5xx/429 that would break the "always answer" UX — see
# _explain_rate_limit_handler below.
limiter = Limiter(key_func=get_remote_address)

# Cities we serve. `slug` must match backend/data/<slug>.geojson and the
# pipeline's CITIES keys. `center`/`zoom` drive the frontend map view.
CITIES = [
    {"slug": "antwerpen", "name": "Antwerp", "center": [4.40, 51.21], "zoom": 12},
    {"slug": "leuven", "name": "Leuven", "center": [4.70, 50.879], "zoom": 13},
]
DEFAULT_CITY = "antwerpen"

# In-memory cache: slug -> pre-serialized GeoJSON bytes (loaded at startup).
_geojson_cache: dict[str, bytes] = {}

# In-memory cache: slug -> pre-serialized points GeoJSON bytes (loaded at
# startup, best-effort). A missing points file leaves the slug absent here, so
# /api/points returns a clear 503.
_points_cache: dict[str, bytes] = {}


def _load_geojson() -> None:
    """Load and cache each city's sector + points GeoJSON as raw bytes.

    Caching the bytes lets us serve them without re-parsing on every request. A
    city whose sector file is missing is simply skipped (omitted from
    /api/cities, 503 on /api/spots), so the service still boots with whatever
    data is present. The points file is best-effort: a missing one is logged and
    skipped (503 on /api/points), independent of the sector data.
    """
    _geojson_cache.clear()
    _points_cache.clear()
    for c in CITIES:
        path = DATA_DIR / f"{c['slug']}.geojson"
        try:
            _geojson_cache[c["slug"]] = path.read_bytes()
            logger.info("Loaded GeoJSON for %s (%d bytes)", c["slug"], len(_geojson_cache[c["slug"]]))
        except (FileNotFoundError, OSError):
            logger.warning("GeoJSON for %s not found at %s — skipping", c["slug"], path)

        points_path = DATA_DIR / f"{c['slug']}_points.geojson"
        try:
            _points_cache[c["slug"]] = points_path.read_bytes()
            logger.info(
                "Loaded points GeoJSON for %s (%d bytes)",
                c["slug"],
                len(_points_cache[c["slug"]]),
            )
        except (FileNotFoundError, OSError):
            logger.warning(
                "Points GeoJSON for %s not found at %s — skipping",
                c["slug"],
                points_path,
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan handler: load and cache the GeoJSON at startup.

    Replaces the deprecated ``@app.on_event("startup")`` hook. Each city's files
    are read once into the per-slug ``_geojson_cache`` / ``_points_cache`` dicts;
    a missing file simply leaves that slug absent from the dict, so ``/api/spots``
    (or ``/api/points``) returns a clear 503 for it.
    """
    _load_geojson()
    yield


app = FastAPI(title="SpotFinder API", version="1.0.0", lifespan=lifespan)

# Attach the rate limiter. We register a CUSTOM rate-limit-exceeded handler
# (see _explain_rate_limit_handler) instead of slowapi's default 429 JSON, so an
# over-limit /api/explain still returns a usable template answer.
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _explain_rate_limit_handler(request: Request, exc) -> JSONResponse:
    """Graceful degradation on rate-limit exceed for /api/explain.

    Instead of the default 429 JSON (which would break the "never 5xx, always
    answer" UX), return the deterministic template explanation with HTTP 200 and
    ``source: "template"`` — exactly the shape the AI path / fallback returns.
    The request body is already parsed-and-validated by the time the limiter
    fires, so we can read the typed model off ``request`` if present; otherwise
    fall back to a generic cafe template.
    """
    from explain import build_template_explanation

    type_ = "cafe"
    lens = None
    props: dict = {}
    # The validated body is not re-exposed on the request here, so rebuild from
    # the raw JSON best-effort. On any parse issue we still answer with a generic
    # template rather than erroring.
    try:
        body = await request.json()
        if isinstance(body, dict):
            if body.get("type") in ("cafe", "bakery", "confectionery"):
                type_ = body["type"]
            raw_lens = body.get("lens")
            if raw_lens in ("vegan", "vegetarian", "glutenfree", "halal"):
                lens = raw_lens
            elif body.get("vegan") is True:
                lens = "vegan"
            if isinstance(body.get("props"), dict):
                props = body["props"]
    except Exception:  # noqa: BLE001 - degrade to a generic template, never 5xx
        pass

    return JSONResponse(
        status_code=200,
        content={
            "explanation": build_template_explanation(type_, lens, props),
            "source": "template",
        },
    )


# --- Security headers + body-size guard --------------------------------------
@app.middleware("http")
async def security_and_size_middleware(request: Request, call_next):
    """Reject oversized /api/explain bodies and set baseline security headers.

    - Body cap: a Content-Length over MAX_EXPLAIN_BODY_BYTES on /api/explain is
      rejected with 413 before FastAPI parses it (cheap cost/DoS guard).
    - Security headers on every response: nosniff, deny framing, a MapLibre-safe
      CSP, and HSTS (prod is always HTTPS). See the CSP notes inline below.
    """
    if request.url.path == "/api/explain":
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > MAX_EXPLAIN_BODY_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large."},
                    )
            except ValueError:
                pass  # malformed header -> let normal parsing reject it

    response = await call_next(request)

    # CSP tuned for the MapLibre SPA served from this same origin. The basemap is
    # CARTO positron (https://basemaps.cartocdn.com/...), which fetches the style
    # JSON, vector tiles, glyphs and sprites over https, and MapLibre renders via
    # web workers (blob:) and decodes tile images (data:/blob:). We therefore
    # allow https: + data: + blob: for img/connect and blob: for workers, while
    # keeping script/style to 'self' (+ 'unsafe-inline' for Vite-injected styles)
    # and framing fully disabled. This is permissive-but-real: it locks down
    # framing and script origins without breaking the map.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "worker-src 'self' blob:; "
        "child-src 'self' blob:; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' https: data: blob:; "
        "font-src 'self' data:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'",
    )
    response.headers.setdefault(
        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
    )
    return response


# --- CORS -------------------------------------------------------------------
# Allowed origins from env FRONTEND_ORIGIN (comma-separated); default "*".
# Prod is single-origin (UI + API same host) so CORS is mostly moot there, but
# we keep "*" only as the LOCAL DEV default and warn loudly when it is in effect.
_frontend_origin = os.environ.get("FRONTEND_ORIGIN", "*").strip()
if _frontend_origin == "*" or not _frontend_origin:
    _allow_origins = ["*"]
    logger.warning(
        "CORS is OPEN to all origins (FRONTEND_ORIGIN unset or '*'). This is fine "
        "for local dev only — set FRONTEND_ORIGIN to your deployed origin in prod."
    )
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
# Bounds on the free-form `props` map: the handler only reads a fixed set of
# small numeric keys, so a strict, capped scalar dict is safe and blocks abuse.
MAX_PROP_KEYS = 40
MAX_PROP_STR_LEN = 200


class ExplainRequest(BaseModel):
    type: Literal["cafe", "bakery", "confectionery"]
    # Allowlisted dietary lenses only (was `str | None`). Unknown/None is handled
    # gracefully downstream by explain.py (LENSES.get / `lens in LENSES`).
    lens: Literal["vegan", "vegetarian", "glutenfree", "halal"] | None = None
    # Legacy: kept for external API back-compat (the current frontend always
    # sends `lens`). Superseded by `lens` when that is provided; see post_explain.
    vegan: bool = False
    props: dict[str, float | int | str | bool | None] = Field(default_factory=dict)

    @field_validator("props")
    @classmethod
    def _bound_props(
        cls, v: dict[str, float | int | str | bool | None]
    ) -> dict[str, float | int | str | bool | None]:
        """Cap the key count and string value length on `props`."""
        if len(v) > MAX_PROP_KEYS:
            raise ValueError(f"props has too many keys (max {MAX_PROP_KEYS})")
        for value in v.values():
            if isinstance(value, str) and len(value) > MAX_PROP_STR_LEN:
                raise ValueError(
                    f"props string value too long (max {MAX_PROP_STR_LEN} chars)"
                )
        return v


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


@app.get("/api/points")
def get_points(city: str = DEFAULT_CITY) -> Response:
    """Return a city's points GeoJSON FeatureCollection (default: Antwerp).

    Mirrors ``get_spots``: served from the in-memory points cache as
    pre-serialized JSON bytes. Returns 503 if that city's points file was
    missing/unloaded at startup.
    """
    data = _points_cache.get(city)
    if data is None:
        raise HTTPException(
            status_code=503,
            detail=f"Points GeoJSON for city '{city}' is not available on the server.",
        )
    return Response(content=data, media_type="application/json")


@app.post("/api/explain")
@limiter.limit("10/minute")
async def post_explain(request: Request, req: ExplainRequest) -> dict:
    """Two-layer zone explainer.

    Tries the Gemini AI layer, falls back to the deterministic template on ANY
    failure. MUST NEVER return a 5xx — the orchestrator never raises, and we
    wrap defensively here as well.

    Rate limited to 10 req/min/IP (the AI layer is billable). On exceed, the
    custom handler returns the template with HTTP 200 instead of a 429 (see
    _explain_rate_limit_handler). The ``request`` param is required by slowapi.
    """
    # Prefer the explicit lens; fall back to the legacy `vegan` bool.
    lens = req.lens if req.lens is not None else ("vegan" if req.vegan else None)
    try:
        return await explain(req.type, lens, req.props)
    except Exception as exc:  # noqa: BLE001 - last-resort guard, never 5xx
        logger.error("Unexpected error in /api/explain, returning template: %s", exc)
        from explain import build_template_explanation

        return {
            "explanation": build_template_explanation(req.type, lens, req.props),
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
