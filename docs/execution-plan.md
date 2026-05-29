# SpotFinder — Execution Plan

Status legend: ✅ done · ⏳ running · ⬜ queued

## Phase 0 — Research ✅
Overpass counts for Antwerp + Statbel dataset availability. Output: [docs/phase0-data-recon.md](phase0-data-recon.md).
Key decisions locked: keep café+bakery; **merge `shop=pastry`+`shop=confectionery`** into one (33, low-confidence); café count is an **upper bound** (bar tags catch only 2/281); **vegan lens GO** (48 tagged) as a post-processor; 4 Statbel URLs verified live (EPSG:31370 → reproject to 4326).

## Phase 1 — Build / Scaffold ✅ (workflow `wl98ee1t0`, 6 agents)
Parallel agents wrote `pipeline/` + `backend/` (FastAPI + AI explainer) + `frontend/` (React/Vite/MapLibre) + synthetic `backend/data/antwerpen.geojson` + root README/.gitignore. First verification: backend boots, all 3 endpoints pass, frontend builds.

## Phase 2 — Harden ✅ (workflow `w6p85ihmr`)
- `pipeline/config.py`: placeholder URLs → **3 verified Statbel URLs** (geometry shp / income xlsx 2023 / population xlsx 2024); CRS + `CD_SECTOR` join-key comments; café upper-bound note.
- Fixed a real miss: `shop=pastry` was under **bakery** → moved into **confectionery** (true pastry+confectionery merge); added `TYPE_LOW_CONFIDENCE`/`CONFECTIONERY_SAMPLE_SIZE=33`.
- `backend/main.py`: deprecated `@app.on_event("startup")` → **lifespan handler**; `render.yaml` PYTHON_VERSION 3.12.7 confirmed; README Python-3.11–3.13 note.

## Phase 3 — Review ∥ Test ✅ (7 agents in parallel)
**Review (read-only):** pipeline 1 high + 3 low · backend 1 medium + 3 low · frontend 3 low (one was a *false* finding — caught and rejected).
**Tests (all passed):** backend boot + 3 endpoints + invalid-type→422; frontend `npm build`; GeoJSON 21-field contract (60 features, opp null ⇔ n_food<3, all norms in [0,1]); pipeline `py_compile` + deterministic sample regen.

## Phase 4 — Fix ✅ (3 agents)
- pipeline: applied the **high** (dropped out-of-spec `shop=chocolate`/`sweets` from confectionery → matches the documented 33). Skipped 3 low (cross-layer / README-scope) with reasons.
- backend: applied the **medium** (round gap before threshold compare → parity with `explainer.js`) + 1 low (label fallback parity). Skipped 2 non-defect low.
- frontend: skipped all 3 low; **correctly rejected a false finding** whose "fix" would have introduced a regression.

## Phase 5 — Final integration re-test ✅ → **finalPass: true** (3 agents)
Clean venv (py3.10) boot → `/health` ok, `/api/spots` 60 features, `/api/explain` 200 `source:"template"` (never 5xx), invalid type → 422; frontend fresh `dist/` build; **schema contract holds end-to-end** (pipeline writes 21 props == backend serves verbatim == frontend reads only contract fields).

---

## Phase 6 — Real data ✅ (workflow `wlqyar621`)
Ran the pipeline against **live Statbel + Overpass** (venv py3.10): `fetch_osm` (5426 OSM elements) → `fetch_statbel` (19,795 sectors reprojected 31370→4326, income year 2023, 458 Antwerp sectors) → `clean` (café 308 / bakery 157 / confectionery 34 ≈ Phase 0's 33; 11 diet:vegan) → `build_grid` (415 H3 res-8 cells) → `compute`.
**`backend/data/antwerpen.geojson` is now REAL: 415 hexes (was 60 synthetic), 38 scorable per type, ~349 KB.** Validation PASS (21-field contract, all norms∈[0,1], opp null ⇔ n_food<3, 0 violations). Real stats: ~711k population over the bbox, median income ~40,392 EUR.
Two real fixes to `fetch_statbel.py`: the geometry sector-code column is `CS01012022` (not `CD_SECTOR`); the income XLSX is a 2005–2023 series → filter to the latest year before averaging.

## Polish ✅ (low findings closed)
- `make_sample.py` percentile now mirrors `compute.py` (single hex → 1.0) — synthetic sample is a faithful proxy again.
- README `n_food` wording tightened (scored types only).
- `Map.jsx` vegan term null-guarded with `coalesce`.

## Committed ✅
Branch `spotfinder/scaffold`, root commit `57d56db`, 37 files (no venv/node_modules/dist/raw downloads). **Not pushed.** `.gitignore` extended to exclude pipeline raw/intermediate downloads while keeping `backend/data/antwerpen.geojson` tracked.

> Note: "22-field contract" = 21 properties + Polygon geometry (reconciled; not a defect).

### Orchestration model
- Each phase ran as a background workflow (deterministic fan-out); user in the loop between phases.
- Ordering: review/test ran only after the build finished; fixes edited disjoint per-layer files; final re-test is the closing barrier and re-confirmed earlier caveats are resolved.
