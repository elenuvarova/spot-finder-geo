# SpotFinder

**Where is there room for one more coffee shop, bakery, or confectionery in Antwerp?**

SpotFinder is an interactive map that surfaces *underserved* food-business demand across Antwerp. It blends open geodata — OpenStreetMap establishments and attractors, Belgian Statbel income and population — into a hexagon grid, then scores each cell for how promising it looks for a new café, bakery, or confectionery, accounting for existing competition. The honest framing runs through the whole product: these are **signals, not guarantees**. The map points you toward zones worth a closer look — a catchment gap here, affluent foot-traffic with little supply there — but every "opportunity" is a hypothesis to validate on foot, not a verdict. Foot-traffic is an explicit *proxy*, the vegan lens is built on a tag that *undercounts* reality, and there is deliberately no rent layer because the open data for it does not exist.

---

## Architecture

SpotFinder is three **isolated layers** that only ever touch each other through one file and one HTTP endpoint:

```
pipeline (OFFLINE)  ──writes──▶  backend/data/antwerpen.geojson  ──served by──▶  backend (Render)  ──fetched by──▶  frontend (MapLibre, static)
```

**Data-flow one-liner:** the pipeline computes everything once, offline, and bakes the result into a single `antwerpen.geojson`; the backend just serves that file plus a thin AI explainer; the frontend renders it on a map.

1. **Pipeline — heavy compute, run offline on a developer machine.** Python + geopandas/shapely/h3. Fetches OSM via Overpass and Statbel datasets, builds the H3 grid, computes every score, and writes the final `backend/data/antwerpen.geojson`. It is **never deployed**.
2. **Backend — serves GeoJSON on Render.** FastAPI. Loads the precomputed GeoJSON into memory at startup and serves it from `GET /api/spots`. Does **no** geospatial computation. Also hosts the AI zone-explainer (`POST /api/explain`).
3. **Frontend — static MapLibre app on Vercel/Netlify.** Vite + React + MapLibre GL JS. A pure static bundle that fetches the GeoJSON and the explanations from the backend. No keys, no server.

### Why the heavy compute is offline

The geopandas/Overpass work is intentionally **not** in a request handler:

- **Render request timeouts.** Reprojecting Statbel geometry, building an H3 grid, and running nearest-neighbour gap queries takes far longer than a web request should — it would blow past Render's timeouts and pin the dyno's memory. Precomputing once sidesteps this entirely; the request path only reads bytes.
- **Overpass rate limits.** Overpass is a shared, free, rate-limited service. Calling it per request would be both abusive and unreliable. We hit it once, offline, politely.

The result: the backend's hot path is "read a cached file from memory and return it" — fast, cheap, and safe on a free dyno.

### Render cold-start note

The backend runs on Render's **free** tier, which **sleeps after inactivity**. The first request after a sleep can take ~30–50s to wake the service. We handle this honestly rather than hiding it:

- A lightweight **`/health`** endpoint exists for **keep-alive pings** (e.g. an external uptime pinger) to reduce how often the service goes cold.
- The frontend uses a **generous fetch timeout** and always shows a **patient loading state** while the backend wakes — **never a white screen**, and a clear "it may be waking up, please retry" message if the wake-up exceeds the timeout.

---

## Stack

| Layer | Tech | Notes |
| --- | --- | --- |
| Pipeline | Python 3, geopandas, shapely, h3, pandas, numpy, requests, openpyxl | Offline only; not deployed |
| Backend | Python 3, FastAPI, Uvicorn, httpx, pydantic v2 | Serves GeoJSON + AI explainer on Render (free) |
| Frontend | JavaScript / JSX, React 18, Vite, **MapLibre GL JS** | Static build on Vercel/Netlify; no Mapbox, no TypeScript |
| AI explainer | Google Gemini REST (`gemini-2.5-flash-lite`) | Backend-only key; template fallback always available |
| Data sources | OpenStreetMap (Overpass), Belgian Statbel open data | See the data table below |

> No TypeScript anywhere. The map library is **MapLibre GL JS only** — never Mapbox.

---

## Why each business type uses a different formula

A single weighted "demand score" would quietly assume that a café, a bakery, and a confectionery all succeed for the same reasons. They don't — so SpotFinder uses **three distinct formulas**, each driven by different inputs (see `pipeline/formulas.py`). Collapsing them into one shared weighted sum is explicitly *not* done.

| Type | Business logic | Driven by | Deliberately ignores |
| --- | --- | --- | --- |
| **Café** | A daytime **destination** — people come to it; passing traffic and spending power matter | `traffic_norm`, `transit_norm`, `income_norm`, penalised by `comp_cafe` | residential density, catchment gap (cafés aren't a home-convenience buy) |
| **Bakery** | A **convenience** good bought near home — residents and an underserved distance gap matter | `residential_norm`, `gap_norm_bakery`, lightly `income_norm`, penalised by `comp_bakery` | traffic, transit, offices |
| **Confectionery** | A **discretionary** treat / light destination — spending power gated on a blend of passing traffic and nearby residents | `income_norm`, blend of `traffic_norm` + `residential_norm`, penalised by `comp_confectionery` | — |

Each formula produces a RAW score; the pipeline then converts RAW into a **within-type percentile** (`opp_<type>`, 0..1), so a café opportunity is ranked against other café cells, not against bakeries. Cells too sparse to score reliably (`n_food < 3`) get a `null` opportunity rather than a misleading number.

---

## AI zone-explainer

When you click a hex, SpotFinder explains *why* it looks promising in plain language. This is a **two-layer** design built for graceful degradation (`backend/explain.py`):

1. **Layer 1 — rule-based template (always on).** A deterministic, jargon-free sentence assembled from the hex's metrics ("Residential area and the nearest bakery is roughly 480m away — a classic catchment gap"). It needs no network, no key, and always works. The frontend ships an identical copy of these rules (`frontend/src/explainer.js`) so it can render instantly and offline.
2. **Layer 2 — Gemini "smart mode".** The backend calls the Gemini REST API for a warmer, more natural 2–3 sentence explanation. On **any** failure — missing key, a **429 `RESOURCE_EXHAUSTED`**, timeout, non-200, or a parse error — it **falls back to the Layer 1 template**. The `/api/explain` endpoint **never returns a 5xx**; it returns `{ explanation, source: "ai" | "template" }` so the UI can label which layer answered.

The **Gemini API key lives only in the backend environment** (`GEMINI_API_KEY`). It is never read, bundled, or sent by the frontend — the browser only ever talks to the backend, which proxies the AI call.

---

## Data: layer → source → fact / proxy

Every layer agrees on the same hex grid and the same GeoJSON contract.

| Layer | Source | Fact or proxy? |
| --- | --- | --- |
| Food establishments (cafés, bakeries, confectioneries) | OSM / Overpass | **Fact** (as mapped in OSM) — used for competition counts and gap distances |
| Attractors (offices, universities, transit) | OSM / Overpass | **Fact** — feeds the traffic proxy, `transit`, and `offices` |
| `traffic` foot-traffic | OSM / Overpass (weighted gastro + retail points in hex + neighbours) | **Proxy** — there is no open per-street footfall feed; we approximate it (see limitations) |
| `diet:vegan` coverage | OSM / Overpass diet tags | **Proxy** — the tag **undercounts** real vegan offering (see limitations) |
| Sector geometry | Statbel (statistical sectors, reprojected from Lambert 72 to WGS84) | **Fact** — the spatial unit income/population are joined on |
| `income` (avg fiscal income, EUR) | Statbel fiscal-income dataset | **Fact** (sector average, not per-hex) |
| `residential` population proxy | Statbel population-by-sector dataset | **Proxy for residential density**, distributed to hexes |

**Honest notes on this table:**
- **`traffic` is a proxy, not measured footfall.** It is a weighted count of gastronomy + retail points in a hex and its neighbours — a stand-in for "how busy this place feels", because open, granular footfall data for Antwerp does not exist.
- **`diet:vegan` undercounts.** Many places that serve vegan options simply aren't tagged in OSM, so `vegan_coverage` is a *lower bound* on real-world availability. The vegan lens copy says so out loud.

---

## The GeoJSON contract

`backend/data/antwerpen.geojson` is a **`FeatureCollection` in WGS84 / EPSG:4326**, one **`Feature` per H3 hex**, `geometry` = `Polygon` (lon, lat order). Every layer (pipeline, backend, frontend) must agree on these `properties`:

| Field | Type | Meaning |
| --- | --- | --- |
| `h3` | string | H3 cell index (the synthetic sample uses ids like `sample-0001`) |
| `traffic` | number | Honest foot-traffic **proxy** (weighted gastro + retail points in hex + neighbours) |
| `transit` | number | Transit access score |
| `offices` | integer | Offices + universities count |
| `residential` | number | Population proxy (Statbel sector) |
| `income` | number | Avg fiscal income, EUR (Statbel sector) |
| `n_food` | integer | Count of the three **scored** food types (café + bakery + confectionery) in hex (noise threshold; also the `vegan_coverage` denominator) |
| `traffic_norm` | number | 0..1 across all hexes |
| `transit_norm` | number | 0..1 |
| `residential_norm` | number | 0..1 |
| `income_norm` | number | 0..1 |
| `comp_cafe` | integer | Café competitors in hex + neighbours |
| `comp_bakery` | integer | Bakery competitors in hex + neighbours |
| `comp_confectionery` | integer | Confectionery competitors in hex + neighbours |
| `gap_cafe` | number | Metres to nearest café |
| `gap_bakery` | number | Metres to nearest bakery |
| `gap_confectionery` | number | Metres to nearest confectionery |
| `opp_cafe` | number \| null | Percentile-normalized 0..1 **within type**; `null` if `n_food < 3` |
| `opp_bakery` | number \| null | As above, for bakery |
| `opp_confectionery` | number \| null | As above, for confectionery |
| `vegan_coverage` | number | 0..1 documented `diet:vegan` coverage (vegan-tagged / total establishments in hex) |

> **The committed `backend/data/antwerpen.geojson` is currently a SYNTHETIC sample** (generated by `pipeline/make_sample.py`) so the app runs end-to-end before any real data has been fetched. It conforms exactly to the contract above but its numbers are made up. Run the pipeline against live OSM/Statbel data to replace it.
>
> The **exact OSM counts and Statbel dataset URLs** are still being collected and recorded in `docs/phase0-data-recon.md`.

---

## Local development

Each layer runs independently. From the **repo root**:

### 1. Pipeline (optional — only to regenerate the GeoJSON)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r pipeline/requirements.txt

# Quick path: write a synthetic sample so the app runs immediately.
python pipeline/make_sample.py            # -> backend/data/antwerpen.geojson

# Full path: build from real data (run the stages in order).
python pipeline/fetch_osm.py              # 1. OSM/Overpass  -> pipeline/data/osm_points_raw.geojson
python pipeline/fetch_statbel.py          # 2. Statbel       -> pipeline/data/statbel_sectors.geojson
python pipeline/clean.py                  # 3. clean/classify-> pipeline/data/osm_points_clean.geojson
python pipeline/build_grid.py             # 4. H3 grid       -> pipeline/data/grid.geojson
python pipeline/compute.py                # 5. scores        -> backend/data/antwerpen.geojson
```

### 2. Backend — Uvicorn on `:8000`

```bash
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env      # optional: add GEMINI_API_KEY for smart mode
cd backend && uvicorn main:app --reload --port 8000
# http://localhost:8000/health   http://localhost:8000/api/spots
```

Without a `GEMINI_API_KEY`, the explainer runs in template-only mode — everything still works.

### 3. Frontend — Vite on `:5173`

```bash
cd frontend
npm install
cp .env.example .env                      # set VITE_API_URL=http://localhost:8000
npm run dev                               # http://localhost:5173
```

`VITE_API_URL` tells the frontend where the backend lives; it defaults to `http://localhost:8000`. **No API key ever belongs in the frontend env** — keys live on the backend only.

---

## Deploy — one free service on Render

The repo-root **`render.yaml`** + **`Dockerfile`** deploy everything as a **single** free web service: a multi-stage Docker build compiles the React/Vite frontend, then FastAPI serves both the API (`/api/*`, `/health`) **and** the built UI from the same origin — so there's no separate frontend host and no CORS to configure.

1. In Render: **New → Blueprint**, connect this repo, pick the **`main`** branch, leave Blueprint Path blank (`render.yaml` is at the root). Render builds the `Dockerfile`.
2. In the service's **Environment** tab set **`GEMINI_API_KEY`** (the `sync: false` secret) to enable Gemini smart mode — leave it unset to run template-only. (`GEMINI_MODEL` defaults to `gemini-2.5-flash-lite`.)
3. Open the service URL — it serves the full app (map + API).

Notes:
- The free service **sleeps** after inactivity (~30–50s cold start on the first hit); point a keep-alive pinger at `/health` to reduce it. The frontend shows a loading state during wake-up.
- Want the frontend on a CDN instead (instant loads, no cold start)? You can still deploy `frontend/` to Vercel/Netlify separately — build `npm run build`, output `dist/`, and set `VITE_API_URL` to the backend URL. The single-service setup above is the default.

---

## Honest limitations

SpotFinder is a decision-*support* tool, and it says so:

- **Traffic is a proxy.** There is no open footfall feed for Antwerp, so `traffic` approximates busyness from the density of gastronomy/retail points. It can mislead in areas that are busy for non-commercial reasons.
- **The vegan tag undercounts.** `vegan_coverage` is built on OSM's `diet:vegan` tag, which is sparsely applied. Real vegan availability is almost certainly higher than what the map shows — treat low coverage as "poorly documented", not "absent".
- **There is no rent layer.** Commercial rent is a huge factor in site selection, but no usable open dataset exists, so SpotFinder simply does not model cost. A "great signal" cell could still be unaffordable.
- **The free Gemini tier is non-commercial in the EU.** The smart-mode explainer uses Google's free Gemini tier, whose terms restrict commercial use in the EU. It is fine for this portfolio/demo context; a production deployment would need a paid tier (and the rule-based template would carry it regardless).

**Signals, not guarantees.** Always verify on the ground.
