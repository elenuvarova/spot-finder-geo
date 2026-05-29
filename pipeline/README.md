# SpotFinder — OFFLINE data pipeline

This pipeline builds `backend/data/antwerpen.geojson`, the H3 opportunity grid
that the SpotFinder backend serves. It reads **OpenStreetMap** (via Overpass)
and **Belgian Statbel** open data, builds an H3 grid over Antwerp, computes
per-type underserved-demand opportunity scores, and writes the GeoJSON in the
exact schema the backend expects.

It is **run manually on a developer machine and is NOT deployed.** It needs
network access and downloads non-trivial files, so you run it occasionally to
refresh the data, not on every request.

## What it produces

A `FeatureCollection` in WGS84 / EPSG:4326, one `Polygon` feature per H3 hex,
with opportunity scores (`opp_cafe`, `opp_bakery`, `opp_confectionery`) plus
the honest input signals (foot-traffic **PROXY**, transit, offices,
residential population proxy, fiscal income, competition counts, distance
gaps, and documented `diet:vegan` coverage).

Important honesty notes baked into the data and the code:

- `traffic` is an **honest PROXY** (weighted gastronomy + retail points in a
  hex and its neighbours), **not** a measured pedestrian count.
- `vegan_coverage` is **documented** `diet:vegan` coverage; the tag
  **undercounts** real-world vegan offerings.
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

Run the stages **in this order** from the repo root (each writes an
intermediate file under `pipeline/data/` that the next stage reads):

```sh
python pipeline/fetch_osm.py       # 1. OSM/Overpass  -> pipeline/data/osm_points_raw.geojson
python pipeline/fetch_statbel.py   # 2. Statbel       -> pipeline/data/statbel_sectors.geojson
python pipeline/clean.py           # 3. clean/classify-> pipeline/data/osm_points_clean.geojson
python pipeline/build_grid.py      # 4. H3 grid       -> pipeline/data/grid.geojson
python pipeline/compute.py         # 5. scores        -> backend/data/antwerpen.geojson
```

The final stage, **`compute.py`, writes `backend/data/antwerpen.geojson`** —
the exact file the backend serves.

## Configuration

Everything tunable lives in `pipeline/config.py`:

- Antwerp bounding box and the Overpass endpoint.
- OSM tag sets per type, the attractor sets, and the `diet:vegan` rule
  (`diet:vegan` in `{yes, only}`; `cuisine=vegan` is intentionally **not** used).
- Statbel dataset URLs. These are best-known `statbel.fgov.be` placeholders;
  the **exact URLs and reference years are confirmed in
  `docs/phase0-data-recon.md`** — update the constants in `config.py` to match.
- H3 resolution (`8`), the per-type formula weights, and thresholds
  (`NOISE_MIN_FOOD = 3`; explainer thresholds `HIGH = 0.6`,
  `GAP_HIGH_M = 400`, `COMP_HIGH = 4`).

## Per-type formulas

The three formulas are intentionally **distinct** (different inputs per type)
and live in `pipeline/formulas.py`. Each `raw` score is percentile-ranked
**within its own type** to produce `opp_<type>` in `0..1`; hexes with
`n_food < 3` are nulled out (`opp_<type> = null`).

- **cafe** (destination / daytime traffic):
  `raw = (traffic_norm + 0.5*transit_norm) * income_norm / (1 + comp_cafe)`
- **bakery** (convenience, bought near home; traffic/offices intentionally NOT used):
  `raw = residential_norm * gap_norm_bakery * (0.5 + 0.5*income_norm) / (1 + comp_bakery)`
- **confectionery** (discretionary, light destination):
  `raw = income_norm * (0.6*traffic_norm + 0.4*residential_norm) / (1 + comp_confectionery)`
