# SpotFinder

**Where is there room for one more coffee shop, bakery, or confectionery?**

🔗 **Live demo:** [foodspotter.ontwrpn.com](https://foodspotter.ontwrpn.com)

SpotFinder is an interactive map that surfaces *underserved* food-business demand across a selectable Belgian city — **Antwerp** (458 statistical sectors) and **Leuven** (176), switchable from the in-app city picker. It blends open geodata — OpenStreetMap establishments and attractors, Belgian Statbel income and population — onto each city's statistical sectors (real neighbourhoods), then scores every sector for how promising it looks for a new café, bakery, or confectionery, accounting for existing competition. Four dietary **lenses** (vegan, vegetarian, gluten-free, halal) re-tint the map by documented diet coverage. The honest framing runs through the whole product: these are **signals, not guarantees**. The map points you toward zones worth a closer look — a catchment gap here, affluent foot-traffic with little supply there — but every "opportunity" is a hypothesis to validate on foot, not a verdict. Foot-traffic is an explicit *proxy*, each diet lens is built on a tag that *undercounts* reality, and there is deliberately no rent layer because the open data for it does not exist.

---

## Architecture

SpotFinder is three **isolated layers** that only ever touch each other through a set of per-city files and a thin HTTP API:

```text
pipeline (OFFLINE)  ──writes──▶  backend/data/<city>.geojson          ──served by──▶  backend (FastAPI)  ──fetched by──▶  frontend (MapLibre, static)
                    ──writes──▶  backend/data/<city>_points.geojson
```

**Data-flow one-liner:** the pipeline computes everything once, offline, per city, and bakes the result into `<city>.geojson` (sectors) + `<city>_points.geojson` (the establishment point layer); the backend just serves those files plus a thin AI explainer; the frontend renders them on a map.

1. **Pipeline — heavy compute, run offline on a developer machine.** Python + geopandas/shapely. For each city (`SF_CITY=antwerpen|leuven`) it fetches OSM via Overpass and Statbel datasets, aggregates everything onto that city's Statbel statistical sectors, computes every score, and writes the final `backend/data/<city>.geojson` plus the per-point `backend/data/<city>_points.geojson`. It is **never deployed**.
2. **Backend — serves the precomputed data.** FastAPI. Loads each city's GeoJSON and point layer into memory at startup and serves them from `GET /api/cities` (the city list + default), `GET /api/spots?city=<slug>` (sector scores), and `GET /api/points?city=<slug>` (establishment points). Does **no** geospatial computation. Also hosts the AI zone-explainer (`POST /api/explain`).
3. **Frontend — static MapLibre app.** Vite + React + MapLibre GL JS. A pure static bundle that fetches the city list, sector GeoJSON, point layer, and explanations from the backend. A **CitySelect** control switches between Antwerp and Leuven; a lens control re-tints by diet coverage. No keys, no server.

### Why the heavy compute is offline

The geopandas/Overpass work is intentionally **not** in a request handler:

- **Request timeouts.** Reprojecting Statbel geometry, aggregating thousands of points onto sectors, and running nearest-neighbour gap queries takes far longer than a web request should — it would blow past any host's request timeouts and pin the container's memory. Precomputing once sidesteps this entirely; the request path only reads bytes.
- **Overpass rate limits.** Overpass is a shared, free, rate-limited service. Calling it per request would be both abusive and unreliable. We hit it once, offline, politely.

The result: the backend's hot path is "read a cached file from memory and return it" — fast, cheap, and safe even on a small free instance.

### Cold-start note (free-tier hosts)

On hosts that **sleep after inactivity** (e.g. Render's free tier), the first request after a sleep can take ~30–50s to wake the service. We handle this honestly rather than hiding it:

- A lightweight **`/health`** endpoint exists for **keep-alive pings** (e.g. an external uptime pinger) to reduce how often the service goes cold.
- The frontend uses a **generous fetch timeout** and always shows a **patient loading state** while the backend wakes — **never a white screen**, and a clear "it may be waking up, please retry" message if the wake-up exceeds the timeout.

---

## Stack

| Layer | Tech | Notes |
| --- | --- | --- |
| Pipeline | Python 3, geopandas, shapely, h3, pandas, numpy, requests, openpyxl | Offline only; not deployed |
| Backend | Python 3, FastAPI, Uvicorn, httpx, pydantic v2 | Serves per-city GeoJSON + point layer + AI explainer; single-service deploy (Coolify / Render) |
| Frontend | JavaScript / JSX, React 18, Vite, **MapLibre GL JS** | Static build, served same-origin by the backend (or a CDN); no Mapbox, no TypeScript |
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

Each formula produces a RAW score; the pipeline then converts RAW into a **within-type percentile** (`opp_<type>`, 0..1), so a café opportunity is ranked against other café cells, not against bakeries. A sector gets a `null` opportunity (rather than a misleading number) unless it clears a **neighbour-aware gate**: it OR a touching neighbour must host at least `NOISE_MIN_FOOD` (= 1) scored-type establishment **and** the sector must be *viable* — `residential > 0` OR `n_food > 0`. The viability test greys out uninhabitable polygons (river / port / pure-infrastructure sectors with no residents and no establishments) instead of colouring them "low opportunity". This is why an empty sector next to a busy street is still scored: it is exactly an underserved candidate. In the committed Antwerp data, 321 of 458 sectors carry a non-null `opp_cafe` even though their *own* `n_food` is below 3.

---

## AI zone-explainer

When you click a neighbourhood, SpotFinder explains *why* it looks promising in plain language. This is a **two-layer** design built for graceful degradation (`backend/explain.py`):

1. **Layer 1 — rule-based template (always on).** A deterministic, jargon-free sentence assembled from the sector's metrics ("Residential area and the nearest bakery is roughly 480m away — a classic catchment gap"). When a diet **lens** is active (vegan / vegetarian / gluten-free / halal), the template adds an honest, lens-aware coverage note for that lens. It needs no network, no key, and always works. The frontend ships an identical copy of these rules (`frontend/src/explainer.js`) so it can render instantly and offline.
2. **Layer 2 — Gemini "smart mode".** The backend calls the Gemini REST API for a warmer, more natural 2–3 sentence explanation. On **any** failure — missing key, a **429 `RESOURCE_EXHAUSTED`**, timeout, non-200, or a parse error — it **falls back to the Layer 1 template**. The `/api/explain` endpoint **never returns a 5xx**; it returns `{ explanation, source: "ai" | "template" }` so the UI can label which layer answered.

The **Gemini API key lives only in the backend environment** (`GEMINI_API_KEY`). It is never read, bundled, or sent by the frontend — the browser only ever talks to the backend, which proxies the AI call.

---

## Data: layer → source → fact / proxy

Every layer agrees on the same sector units and the same GeoJSON contract.

| Layer | Source | Fact or proxy? |
| --- | --- | --- |
| Food establishments (cafés, bakeries, confectioneries) | OSM / Overpass | **Fact** (as mapped in OSM) — used for competition counts and gap distances |
| Attractors (offices, universities, transit) | OSM / Overpass | **Fact** — feeds the traffic proxy, `transit`, and `offices` |
| `traffic` foot-traffic | OSM / Overpass (weighted gastro + retail points in the sector) | **Proxy** — there is no open per-street footfall feed; we approximate it (see limitations) |
| Diet coverage (`vegan` / `vegetarian` / `glutenfree` / `halal`) | OSM / Overpass `diet:*` tags | **Proxy** — every `diet:*` tag **undercounts** real offering (see limitations) |
| Sector geometry | Statbel (statistical sectors, reprojected from Lambert 72 to WGS84) | **Fact** — the spatial unit income/population are joined on |
| `income` (avg fiscal income, EUR) | Statbel fiscal-income dataset | **Fact** (native sector average) |
| `residential` population | Statbel population-by-sector dataset | **Native** sector population |

**Honest notes on this table:**
- **`traffic` is a proxy, not measured footfall.** It is a weighted count of gastronomy + retail points in the sector — a stand-in for "how busy this place feels", because open, granular footfall data for these cities does not exist.
- **The `diet:*` tags undercount.** Many places that serve vegan / vegetarian / gluten-free / halal options simply aren't tagged in OSM, so each `*_coverage` is a *lower bound* on real-world availability. Each lens's copy says so out loud.

---

## The GeoJSON contract

Each `backend/data/<city>.geojson` is a **`FeatureCollection` in WGS84 / EPSG:4326**, one **`Feature` per Statbel statistical sector**, `geometry` = `Polygon` or `MultiPolygon` (lon, lat order). Every layer (pipeline, backend, frontend) must agree on these `properties`:

| Field | Type | Meaning |
| --- | --- | --- |
| `unit_id` | string | Statbel statistical-sector code, e.g. `11002A00-` (the dev sample uses ids like `sample-0001`) |
| `traffic` | number | Honest foot-traffic **proxy** (weighted gastro + retail points in the sector) |
| `transit` | number | Transit access score |
| `offices` | integer | Offices + universities count |
| `residential` | number | Population proxy (Statbel sector) |
| `income` | number | Avg fiscal income, EUR (Statbel sector) |
| `n_food` | integer | Count of the three **scored** food types (café + bakery + confectionery) in the sector. The diet-coverage denominator is broader: documented **eateries** (scored types + gastro attractors). |
| `traffic_norm` | number | 0..1 across all sectors |
| `transit_norm` | number | 0..1 |
| `residential_norm` | number | 0..1 |
| `income_norm` | number | 0..1 |
| `comp_cafe` | integer | Café competitors in the sector |
| `comp_bakery` | integer | Bakery competitors in the sector |
| `comp_confectionery` | integer | Confectionery competitors in the sector |
| `gap_cafe` | number | Metres to nearest café |
| `gap_bakery` | number | Metres to nearest bakery |
| `gap_confectionery` | number | Metres to nearest confectionery |
| `opp_cafe` | number \| null | Percentile-normalized 0..1 **within type**; `null` unless the sector clears the neighbour-aware gate (see below) |
| `opp_bakery` | number \| null | As above, for bakery |
| `opp_confectionery` | number \| null | As above, for confectionery |
| `vegan_coverage` | number | 0..1 documented `diet:vegan` coverage (vegan-tagged / documented eateries in the sector) |
| `vegetarian_coverage` | number | 0..1 documented `diet:vegetarian` coverage |
| `glutenfree_coverage` | number | 0..1 documented `diet:gluten_free` coverage |
| `halal_coverage` | number | 0..1 documented `diet:halal` coverage |

**`opp_<type>` gate (when is a sector scored vs. `null`?):** a sector is scored only if (a) it OR a touching neighbour holds at least `NOISE_MIN_FOOD` (= 1) scored-type establishment (the **neighbour-aware** activity test, so an empty sector next to activity is still a candidate) **and** (b) it is *habitable* — `residential > 0` OR `n_food > 0`. Uninhabitable polygons (river / port / pure-infrastructure: 0 residents and 0 establishments) are `null` (greyed out) even when a neighbour has food. Note this is **not** a per-sector `n_food >= 3` rule: 321 of 458 Antwerp sectors carry a non-null `opp_cafe` despite their own `n_food` being below 3.

> **The committed `backend/data/*.geojson` is REAL data**, built by the pipeline from live OpenStreetMap (Overpass) and Belgian Statbel open data — not a synthetic sample. Antwerp (`antwerpen.geojson`, 458 sectors) and Leuven (`leuven.geojson`, 176 sectors) ship with all four diet coverages populated, plus matching `<city>_points.geojson` point layers. `pipeline/make_sample.py` exists only as a quick offline fixture (it writes to `backend/data/sample.geojson` so it never clobbers a real city); it reuses the same formulas, percentile ranking, and gate as the real pipeline so the schema and math cannot drift.
>
> Source provenance (OSM counts and Statbel dataset URLs) is recorded in `docs/phase0-data-recon.md`.

---

## Local development

Each layer runs independently. From the **repo root**:

### 1. Pipeline (optional — the real data is already committed)

Real `backend/data/<city>.geojson` files ship in the repo, so you only run the
pipeline to **refresh** the data or add a city. It is run **per city** via the
`SF_CITY` env var (`antwerpen` is the default; `leuven` is the other).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r pipeline/requirements.txt

# Quick path: write a small synthetic fixture so the app runs without the full
# build. It writes backend/data/sample.geojson and never clobbers a real city.
python pipeline/make_sample.py            # -> backend/data/sample.geojson

# Full path: build a city from real data (run the stages in order, per city).
SF_CITY=antwerpen python pipeline/fetch_osm.py       # 1. OSM/Overpass  -> pipeline/data/<city>_osm_points_raw.geojson
SF_CITY=antwerpen python pipeline/fetch_statbel.py   # 2. Statbel       -> pipeline/data/<city>_statbel_sectors.geojson
SF_CITY=antwerpen python pipeline/clean.py           # 3. clean/classify-> pipeline/data/<city>_osm_points_clean.geojson
SF_CITY=antwerpen python pipeline/build_grid.py      # 4. sector aggregates -> pipeline/data/<city>_grid.geojson
SF_CITY=antwerpen python pipeline/compute.py         # 5. scores        -> backend/data/<city>.geojson
SF_CITY=antwerpen python pipeline/emit_points.py     # 6. point layer   -> backend/data/<city>_points.geojson
# repeat with SF_CITY=leuven for the other city.
```

### 2. Backend — Uvicorn on `:8000`

```bash
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env      # optional: add GEMINI_API_KEY for smart mode
cd backend && uvicorn main:app --reload --port 8000
# http://localhost:8000/health
# http://localhost:8000/api/cities
# http://localhost:8000/api/spots?city=antwerpen
# http://localhost:8000/api/points?city=antwerpen
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

## Deploy — one single service

SpotFinder deploys as a **single** web service: the repo-root **`Dockerfile`** runs a multi-stage build that compiles the React/Vite frontend, then FastAPI serves both the API (`/api/*`, `/health`) **and** the built UI from the same origin — so there's no separate frontend host and no CORS to configure.

**Live:** the app is deployed this way at **[foodspotter.ontwrpn.com](https://foodspotter.ontwrpn.com)** (Coolify, self-hosted). Build the `Dockerfile`, point a subdomain at it, and set the env vars below.

### On Render (free tier, `render.yaml` provided)

1. In Render: **New → Blueprint**, connect this repo, pick the **`main`** branch, leave Blueprint Path blank (`render.yaml` is at the root). Render builds the `Dockerfile`.
2. In the service's **Environment** tab set **`GEMINI_API_KEY`** (the `sync: false` secret) to enable Gemini smart mode — leave it unset to run template-only. (`GEMINI_MODEL` defaults to `gemini-2.5-flash-lite`.)
3. Open the service URL — it serves the full app (map + API).

Notes:
- A free service **sleeps** after inactivity (~30–50s cold start on the first hit); point a keep-alive pinger at `/health` to reduce it. The frontend shows a loading state during wake-up. (The Coolify deploy above does not sleep.)
- Want the frontend on a CDN instead (instant loads, no cold start)? You can still deploy `frontend/` to Vercel/Netlify separately — build `npm run build`, output `dist/`, and set `VITE_API_URL` to the backend URL. The single-service setup above is the default.

---

## Honest limitations

SpotFinder is a decision-*support* tool, and it says so:

- **Traffic is a proxy.** There is no open footfall feed for these cities, so `traffic` approximates busyness from the density of gastronomy/retail points. It can mislead in areas that are busy for non-commercial reasons.
- **The diet tags undercount.** Every diet coverage (`vegan` / `vegetarian` / `glutenfree` / `halal`) is built on OSM's `diet:*` tags, which are sparsely applied. Real availability is almost certainly higher than what the map shows — treat low coverage as "poorly documented", not "absent". The gluten-free and halal lenses are the sparsest of the four.
- **There is no rent layer.** Commercial rent is a huge factor in site selection, but no usable open dataset exists, so SpotFinder simply does not model cost. A "great signal" cell could still be unaffordable.
- **The free Gemini tier is non-commercial in the EU.** The smart-mode explainer uses Google's free Gemini tier, whose terms restrict commercial use in the EU. It is fine for this portfolio/demo context; a production deployment would need a paid tier (and the rule-based template would carry it regardless).

**Signals, not guarantees.** Always verify on the ground.
