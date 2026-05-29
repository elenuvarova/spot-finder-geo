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

## Remaining (Phase 6 — real data, not yet run)
The only thing left is running the **real pipeline against live data** (CI used the synthetic sample by design — needs network + ~50 MB Statbel + Overpass):
1. `cd pipeline` → venv (Python 3.11–3.13) → `pip install -r requirements.txt` → run `fetch_osm → fetch_statbel → clean → build_grid → compute`, writing the real `backend/data/antwerpen.geojson`.
2. **De-risk before that run:** confirm the fiscal-income column name in `fetch_statbel.py` against the real XLSX header (flagged candidate: `MS_AVG_TOT_NET_TAXABLE_INC`) using the Statbel "Columns description" files.

## Known minor items (low, deferred — all honor the contract)
- `compute.py` vs `make_sample.py` percentile convention differs for the single-qualifying-hex edge (1.0 vs 0.0); the synthetic sample is therefore a near- but not exact-proxy of real output.
- "22-field contract" = 21 properties + Polygon geometry (reconciled; not a defect).

### Orchestration model
- Each phase ran as a background workflow (deterministic fan-out); user in the loop between phases.
- Ordering: review/test ran only after the build finished; fixes edited disjoint per-layer files; final re-test is the closing barrier and re-confirmed earlier caveats are resolved.
