"""Central configuration for the SpotFinder OFFLINE data pipeline.

This module is the single source of truth for bounding boxes, data-source
endpoints, OSM tag sets, the H3 resolution, the opportunity-formula weights,
and the noise/explainer thresholds.

The pipeline is run MANUALLY on a developer machine and is NOT deployed.
"""

# ---------------------------------------------------------------------------
# Geography: selectable city (Antwerp, Leuven, ...)
# ---------------------------------------------------------------------------
import os

# Each city: bbox as (south_lat, west_lon, north_lat, east_lon) — Overpass
# "bbox" ordering, used for the OSM query and the Statbel clip — plus a human
# name and the frontend map view (center [lon, lat], zoom).
CITIES = {
    "antwerpen": {
        "name": "Antwerp",
        "bbox": (51.143, 4.270, 51.290, 4.500),
        "center": [4.40, 51.21],
        "zoom": 12,
    },
    "leuven": {
        "name": "Leuven",
        "bbox": (50.840, 4.640, 50.925, 4.760),
        "center": [4.70, 50.879],
        "zoom": 13,
    },
}

# Active city, chosen via the SF_CITY env var so each stage runs per city:
#   SF_CITY=leuven python pipeline/fetch_osm.py   (etc.)
CITY = os.environ.get("SF_CITY", "antwerpen").strip().lower()
if CITY not in CITIES:
    raise SystemExit(f"Unknown SF_CITY={CITY!r}; known cities: {list(CITIES)}")
CITY_NAME = CITIES[CITY]["name"]
BBOX = CITIES[CITY]["bbox"]   # (south, west, north, east) for the active city


def overpass_bbox_str():
    """Return the active city's bbox as the comma string Overpass expects: S,W,N,E."""
    s, w, n, e = BBOX
    return f"{s},{w},{n},{e}"


# ---------------------------------------------------------------------------
# Overpass (OpenStreetMap) endpoint
# ---------------------------------------------------------------------------
# Primary public Overpass endpoint. Mirrors can be swapped in if it is busy.
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Networking politeness: Overpass is a shared free service.
OVERPASS_TIMEOUT_S = 180          # server-side query timeout passed in QL
HTTP_TIMEOUT_S = 300              # client-side socket timeout for requests
HTTP_MAX_RETRIES = 5             # retries on HTTP 429 / 5xx
HTTP_BACKOFF_BASE_S = 5.0        # exponential backoff base (5, 10, 20, ...)
USER_AGENT = "SpotFinder-pipeline/1.0 (offline dev tool; contact: dev@spotfinder.local)"


# ---------------------------------------------------------------------------
# Business types we score (the THREE SpotFinder types)
# ---------------------------------------------------------------------------
# Canonical internal type names. These strings appear verbatim in the GeoJSON
# property names (comp_<type>, gap_<type>, opp_<type>).
TYPES = ("cafe", "bakery", "confectionery")

# OSM tag sets that define each type. A node/way/relation matches a type if it
# carries ANY of the (key, value) pairs listed for that type. We keep these as
# lists of (key, value) tuples so the matching logic in clean.py is trivial.
#
# NOTE on classification order: clean.py iterates this dict in insertion order
# and assigns the FIRST matching type. cafe -> bakery -> confectionery. A shop
# is never both, so the order only matters for tags that could plausibly
# co-occur; it does not here.
OSM_TYPE_TAGS = {
    # amenity=cafe captures coffee shops / cafes. Belgian "cafe-bars" (pubs)
    # are ALSO tagged amenity=cafe in OSM and are filtered out in clean.py.
    "cafe": [
        ("amenity", "cafe"),
        ("shop", "coffee"),          # dedicated coffee retailers / roasteries
    ],
    # Bakeries: bread shops bought near home. (shop=pastry is NOT here: Phase 0
    # merges pastry into the confectionery type below.)
    "bakery": [
        ("shop", "bakery"),
    ],
    # Confectionery: discretionary treats. Phase 0 (docs/phase0-data-recon.md
    # §1, §6) MERGES shop=pastry (19) + shop=confectionery (14) into this ONE
    # type (33 combined) -- and ONLY those two tags. shop=chocolate / shop=sweets
    # are NOT part of the verified Phase 0 merge and are deliberately excluded so
    # the scored population matches the documented 33-establishment sample (and
    # CONFECTIONERY_SAMPLE_SIZE below). See CONFECTIONERY_LOW_CONFIDENCE: this
    # merged type is a thin sample and must be surfaced as LOW-CONFIDENCE
    # downstream.
    "confectionery": [
        ("shop", "pastry"),          # patisserie (merged in from pastry, Phase 0)
        ("shop", "confectionery"),
    ],
}

# Phase 0 flagged the merged confectionery type (shop=pastry + shop=confectionery
# = 33 establishments in Antwerp) as a THIN sample: percentile normalization is
# noisier and opportunity scores for this type are less reliable than cafe (288)
# or bakery (137). This flag is surfaced by the backend/UI so users see the
# "lower-confidence" caveat for confectionery results. It does NOT change any
# formula math; it is a presentation/honesty signal only.
# Map of type -> is-low-confidence. Downstream (backend/UI) reads this.
TYPE_LOW_CONFIDENCE = {
    "cafe": False,
    "bakery": False,
    "confectionery": True,   # thin sample of 33 (pastry 19 + confectionery 14)
}
# Convenience constant for the one low-confidence type Phase 0 identified.
CONFECTIONERY_LOW_CONFIDENCE = True
CONFECTIONERY_SAMPLE_SIZE = 33   # pastry 19 + confectionery 14 (Antwerp, Phase 0)

# Tags whose presence on an amenity=cafe marks it as a Belgian "cafe-bar"
# (a pub / drinking establishment), which we DROP from the cafe type because
# SpotFinder is about coffee/daytime destinations, not nightlife bars.
# clean.py drops a cafe if it has bar=yes, an alcohol-ish cuisine, real_ale,
# or microbrewery=yes.
#
# HONESTY CAVEAT (Phase 0, docs/phase0-data-recon.md): in Belgium amenity=cafe
# is routinely mapped onto bars/pubs, but EXPLICIT alcohol tags catch only
# ~2 of 281 Antwerp cafes (~0.7%). So this filter is a FLOOR, not a fix, and
# the resulting cafe count is an UPPER BOUND on real coffee destinations. Keep
# the filter (it removes obvious bars cheaply) but frame the cafe count
# honestly downstream as an upper bound ("signals, not guarantees").
CAFE_BAR_DROP = {
    "bar": {"yes"},                       # bar=yes
    "real_ale": {"yes", "only", "sometimes"},
    "microbrewery": {"yes", "only"},
    "brewery": {"yes", "any", "various"},
}
# cuisine values (semicolon-separated in OSM) that indicate a drinking venue.
CAFE_BAR_ALCOHOL_CUISINES = {"beer", "pub", "bar", "wine", "brewery"}


# ---------------------------------------------------------------------------
# Attractors (foot-traffic PROXY inputs and demand drivers)
# ---------------------------------------------------------------------------
# These are NOT scored types; they feed the honest traffic PROXY, the transit
# score, and the office/university count.
#
# "Gastro + retail" points are the honest foot-traffic PROXY: places that pull
# pedestrians past a storefront during the day. We deliberately call this a
# PROXY everywhere because we do NOT have measured pedestrian counts.
ATTRACTOR_TAGS = {
    # Gastronomy that generates daytime/all-day footfall (eat-in/takeaway).
    "gastro": [
        ("amenity", "restaurant"),
        ("amenity", "fast_food"),
        ("amenity", "food_court"),
        ("amenity", "ice_cream"),
    ],
    # General retail that pulls shoppers down a street.
    "retail": [
        ("shop", "supermarket"),
        ("shop", "convenience"),
        ("shop", "clothes"),
        ("shop", "department_store"),
        ("shop", "mall"),
        ("shop", "greengrocer"),
        ("shop", "butcher"),
        ("shop", "books"),
        ("shop", "deli"),
    ],
    # Public-transport stops/stations -> transit access score.
    "transit": [
        ("public_transport", "station"),
        ("public_transport", "stop_position"),
        ("railway", "station"),
        ("railway", "tram_stop"),
        ("highway", "bus_stop"),
    ],
    # Offices + universities -> daytime worker/student demand.
    "offices": [
        ("office", "*"),               # any office=* value
        ("amenity", "university"),
        ("amenity", "college"),
    ],
}

# Relative weights for the traffic PROXY: a retail storefront and a gastro
# venue are treated as comparable footfall generators, with gastro weighted a
# little higher because food/drink venues drive more frequent passing trips.
TRAFFIC_PROXY_WEIGHTS = {
    "gastro": 1.0,
    "retail": 0.7,
}


# ---------------------------------------------------------------------------
# Diet signals (vegan + the wider diet lenses)
# ---------------------------------------------------------------------------
# We derive a vegan flag from the documented diet:vegan tag ONLY.
# IMPORTANT: cuisine=vegan is explicitly NOT used (it is unreliable / means
# something different). The diet:vegan tag undercounts real-world vegan
# offerings, so vegan_coverage is a DOCUMENTED-coverage signal, not ground truth.
VEGAN_DIET_TAG = "diet:vegan"
VEGAN_POSITIVE_VALUES = {"yes", "only"}   # diet:vegan in {yes, only}

# The full set of diet LENSES. Each lens flags an eatery from a documented
# diet:* tag (value in the lens 'values' set). Like vegan, every diet:* tag
# UNDERCOUNTS reality, so the derived coverages are DOCUMENTED-coverage signals,
# never demand/quality. Keys here are the canonical lens slugs shared with the
# frontend / backend.
DIET_LENSES = {
    "vegan":      {"tag": "diet:vegan",       "values": {"yes", "only"}},
    "vegetarian": {"tag": "diet:vegetarian",  "values": {"yes", "only"}},
    "glutenfree": {"tag": "diet:gluten_free", "values": {"yes", "only"}},
    "halal":      {"tag": "diet:halal",        "values": {"yes", "only"}},
}


# ---------------------------------------------------------------------------
# Statbel (Belgian federal statistics) open-data datasets
# ---------------------------------------------------------------------------
# THREE verified-live direct download URLs (Phase 0, docs/phase0-data-recon.md;
# each confirmed HTTP 200 via curl -sIL on 2026-05-29).
#
# Source CRS: the geometry shapefile is EPSG:31370 (Belgian Lambert 72) and is
# REPROJECTED to WGS84 (EPSG:4326) in fetch_statbel.py via gdf.to_crs(4326).
# Join key across all three datasets: CD_SECTOR (see STATBEL_SECTOR_CODE_FIELD
# below; confirm against the Statbel "Columns description" helper files). NOTE:
# since 2019-01-01 the commune (NIS) code is NOT derivable from the sector code.
STATBEL_SECTOR_GEOMETRY_URL = (
    # Statistical sectors GEOMETRY shapefile (zipped), EPSG:31370 Lambert 72,
    # 2022 vintage. Smaller than the geojson variant; reprojected to 4326.
    "https://statbel.fgov.be/sites/default/files/files/opendata/Statistische%20sectoren/sh_statbel_statistical_sectors_31370_20220101.shp.zip"
)
STATBEL_INCOME_URL = (
    # Fiscal INCOME per statistical sector (xlsx), series through income year 2023.
    "https://statbel.fgov.be/sites/default/files/files/opendata/arbeid%20per%20sector/TF_PSNL_INC_TAX_SECTOR.xlsx"
)
STATBEL_POPULATION_URL = (
    # POPULATION per statistical sector (xlsx), 2024.
    "https://statbel.fgov.be/sites/default/files/files/opendata/bevolking/sectoren/OPENDATA_SECTOREN_2024.xlsx"
)

# Source projection of the Statbel geometry. We REPROJECT to WGS84 (4326)
# in fetch_statbel.py via gdf.to_crs(4326).
STATBEL_SOURCE_CRS = "EPSG:31370"   # Belgian Lambert 72
OUTPUT_CRS = "EPSG:4326"            # WGS84 lon/lat (the GeoJSON contract)

# Column names used when joining the three Statbel tables by sector code.
# The geometry layer's sector-code field and the statistics tables' code field
# must be reconciled to this canonical name during the join. CD_SECTOR is the
# verified join key across all three Phase 0 datasets (confirm against the
# Statbel "Columns description" files).
STATBEL_SECTOR_CODE_FIELD = "CD_SECTOR"   # canonical sector-code / join key
STATBEL_POPULATION_FIELD = "POPULATION"   # canonical population column
STATBEL_INCOME_FIELD = "MEAN_INCOME"      # canonical avg fiscal income (EUR)


# ---------------------------------------------------------------------------
# H3 grid
# ---------------------------------------------------------------------------
# Resolution 9 ~ 0.10 km^2 hexes (edge ~0.17 km): neighbourhood-block scale,
# finer than res 8. Going below res 9 hits two data floors: Statbel income/
# population is constant within a sector (~hundreds of m), and smaller hexes
# hold fewer establishments so more get nulled by the NOISE_MIN_FOOD gate.
H3_RESOLUTION = 9


# ---------------------------------------------------------------------------
# Formula weights / tunables
# ---------------------------------------------------------------------------
# These mirror the PER-TYPE FORMULAS in the spec. They live here so the three
# distinct formulas in formulas.py read off named weights rather than magic
# numbers. Each type has DIFFERENT inputs on purpose.
FORMULA_WEIGHTS = {
    "cafe": {
        # raw = (traffic_norm + TRANSIT_WEIGHT*transit_norm) * income_norm / (1+comp_cafe)
        "transit_weight": 0.5,
    },
    "bakery": {
        # raw = residential_norm * gap_norm_bakery
        #       * (INCOME_FLOOR + INCOME_SPAN*income_norm) / (1+comp_bakery)
        "income_floor": 0.5,
        "income_span": 0.5,
    },
    "confectionery": {
        # raw = income_norm * (TRAFFIC_WEIGHT*traffic_norm
        #       + RESIDENTIAL_WEIGHT*residential_norm) / (1+comp_confectionery)
        "traffic_weight": 0.6,
        "residential_weight": 0.4,
    },
}


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
# Noise gate, applied NEIGHBOUR-AWARE in compute.py: a sector is scored only if
# it OR a touching neighbour has at least this many scored-type establishments
# (see n_food_area in build_grid). A low value keeps the map well "filled" while
# leaving truly isolated empty sectors (no food in or around them) grey.
# NOTE: compute.py ANDs this activity gate with a VIABILITY test
# (residential > 0 OR n_food > 0) so uninhabitable polygons — river / port /
# pure-infra sectors with 0 residents and 0 establishments — are NULLed out
# (greyed, not scored red) even when a neighbour has food: you cannot open a
# business there.
NOISE_MIN_FOOD = 1

# Explainer thresholds (used by the backend / frontend to phrase WHY a hex
# scores well; defined here so the whole project agrees on the cutoffs).
EXPLAINER_HIGH = 0.6        # a *_norm driver at/above this counts as "high"
EXPLAINER_GAP_HIGH_M = 400  # a gap at/above this many metres counts as "big gap"
EXPLAINER_COMP_HIGH = 4     # comp at/above this counts as "crowded / lots of competition"


# ---------------------------------------------------------------------------
# Pipeline file paths (per active CITY; pipeline is run from repo root)
# ---------------------------------------------------------------------------
PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(PIPELINE_DIR)
DATA_DIR = os.path.join(PIPELINE_DIR, "data")   # intermediate artefacts

# Per-city intermediate artefacts (prefixed so cities never clobber each other).
OSM_POINTS_PATH = os.path.join(DATA_DIR, f"{CITY}_osm_points_raw.geojson")
CLEAN_POINTS_PATH = os.path.join(DATA_DIR, f"{CITY}_osm_points_clean.geojson")
STATBEL_SECTORS_PATH = os.path.join(DATA_DIR, f"{CITY}_statbel_sectors.geojson")
GRID_PATH = os.path.join(DATA_DIR, f"{CITY}_grid.geojson")

# FINAL output: backend/data/<city>.geojson — the exact file the backend serves.
OUTPUT_GEOJSON_PATH = os.path.join(REPO_ROOT, "backend", "data", f"{CITY}.geojson")

# FINAL per-point output: backend/data/<city>_points.geojson — the point layer
# the backend serves at /api/points (one feature per cleaned OSM point).
POINTS_OUTPUT_PATH = os.path.join(REPO_ROOT, "backend", "data", f"{CITY}_points.geojson")
