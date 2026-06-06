# SpotFinder — OFFLINE data pipeline

This pipeline builds the per-city files the SpotFinder backend serves:
`backend/data/<city>.geojson` (the per-sector opportunity layer) and
`backend/data/<city>_points.geojson` (the establishment point layer). It reads
**OpenStreetMap** (via Overpass) and **Belgian Statbel** open data, aggregates
everything onto the city's statistical sectors (real neighbourhoods), computes
per-type underserved-demand opportunity scores, and writes the GeoJSON in the
exact schema the backend expects.

It runs **per city**, selected with the `SF_CITY` env var (`antwerpen` default,
`leuven` the other; see `CITIES` in `config.py`):

```sh
SF_CITY=antwerpen python pipeline/compute.py
SF_CITY=leuven    python pipeline/compute.py
```

It is **run manually on a developer machine and is NOT deployed.** It needs
network access and downloads non-trivial files, so you run it occasionally to
refresh the data, not on every request. The real outputs are committed, so a
fresh clone runs without ever invoking the pipeline.

## What it produces

A `FeatureCollection` in WGS84 / EPSG:4326, one `Polygon`/`MultiPolygon` feature
per Statbel statistical sector, with opportunity scores (`opp_cafe`, `opp_bakery`,
`opp_confectionery`) plus the honest input signals (foot-traffic **PROXY**,
transit, offices, residential population proxy, fiscal income, competition
counts, distance gaps, and the four documented diet coverages —
`vegan` / `vegetarian` / `glutenfree` / `halal`). `emit_points.py` additionally
writes the per-point layer (`<city>_points.geojson`).

Important honesty notes baked into the data and the code:

- `traffic` is an **honest PROXY** (weighted gastronomy + retail points in the
  sector), **not** a measured pedestrian count.
- Each `*_coverage` is **documented** `diet:*` coverage; every diet tag
  **undercounts** real-world offerings.
- Scores are **signals, not guarantees.**

## Requirements

- Python 3.10+
- A working GDAL stack for GeoPandas (installing `geopandas` from PyPI pulls
  in a prebuilt `shapely`/`pyogrio` on most platforms; on macOS/Linux this
  generally works out of the box).

## Setup

```sh
# from the repo root
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r pipeline/requirements.txt
```

## Run order

Run the stages **in this order** from the repo root, setting `SF_CITY` for the
city you are building (each writes a per-city intermediate file under
`pipeline/data/` that the next stage reads):

```sh
export SF_CITY=antwerpen            # or leuven
python pipeline/fetch_osm.py       # 1. OSM/Overpass  -> pipeline/data/<city>_osm_points_raw.geojson
python pipeline/fetch_statbel.py   # 2. Statbel       -> pipeline/data/<city>_statbel_sectors.geojson
python pipeline/clean.py           # 3. clean/classify-> pipeline/data/<city>_osm_points_clean.geojson
python pipeline/build_grid.py      # 4. sector aggregates -> pipeline/data/<city>_grid.geojson
python pipeline/compute.py         # 5. scores        -> backend/data/<city>.geojson
python pipeline/emit_points.py     # 6. point layer   -> backend/data/<city>_points.geojson
```

The scoring stage, **`compute.py`, writes `backend/data/<city>.geojson`** and
**`emit_points.py` writes `backend/data/<city>_points.geojson`** — the exact
files the backend serves at `/api/spots` and `/api/points`.

`make_sample.py` is a separate convenience: it writes a small synthetic
`backend/data/sample.geojson` (override with `--out`) for running the app without
a full build. It imports the same formulas, percentile ranking, and gate as the
real pipeline, so the sample schema and math cannot drift from `compute.py`.

## Configuration

Everything tunable lives in `pipeline/config.py`:

- The selectable `CITIES` (Antwerp, Leuven): bounding box, map center/zoom, and
  the active city via `SF_CITY`.
- OSM tag sets per type, the attractor sets, and the four diet **lenses**
  (`DIET_LENSES`: vegan / vegetarian / gluten-free / halal, each from its
  documented `diet:*` tag in `{yes, only}`; `cuisine=*` is intentionally **not**
  used).
- Statbel dataset URLs (verified-live `statbel.fgov.be` downloads; see
  `docs/phase0-data-recon.md` for provenance).
- The per-type formula weights and thresholds
  (`NOISE_MIN_FOOD = 1`; explainer thresholds `HIGH = 0.6`,
  `GAP_HIGH_M = 400`, `COMP_HIGH = 4`).

## Per-type formulas

The three formulas are intentionally **distinct** (different inputs per type)
and live in `pipeline/formulas.py`. Each `raw` score is percentile-ranked
**within its own type** to produce `opp_<type>` in `0..1`. A sector is nulled
out (`opp_<type> = null`) unless it clears a **neighbour-aware** gate: it OR a
touching neighbour holds at least `NOISE_MIN_FOOD` (= 1) scored-type
establishment (`n_food_area >= NOISE_MIN_FOOD`) **and** the sector is habitable
(`residential > 0` OR `n_food > 0`). The viability test greys out uninhabitable
polygons (river / port / pure-infra) instead of scoring them. This is **not** a
per-sector `n_food >= 3` rule.

- **cafe** (destination / daytime traffic):
  `raw = (traffic_norm + 0.5*transit_norm) * income_norm / (1 + comp_cafe)`
- **bakery** (convenience, bought near home; traffic/offices intentionally NOT used):
  `raw = residential_norm * gap_norm_bakery * (0.5 + 0.5*income_norm) / (1 + comp_bakery)`
- **confectionery** (discretionary, light destination):
  `raw = income_norm * (0.6*traffic_norm + 0.4*residential_norm) / (1 + comp_confectionery)`
