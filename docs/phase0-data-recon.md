# Phase 0 — Data Reconnaissance: SpotFinder Antwerp

**Goal:** Identify "underserved demand" zones in Antwerp (Antwerpen, Belgium) for coffee shops (cafés), bakeries, confectioneries (pastry), plus an optional "vegan" lens.

**Scope:** Reconnaissance only — concrete numbers + verify open-data downloads. No application code.

**Date of recon:** 2026-05-29

**Legend:** `[VERIFIED]` = confirmed by live query/curl in this run. `[UNVERIFIED]` = found on a page/docs but not directly confirmed by inspecting file contents.

---

## 1. Summary table: business type → count → verdict

All counts `[VERIFIED]` via live Overpass `out count;` over the Antwerp **municipality** (admin_level=8, exactly 1 boundary matched).

| Business type | OSM tag(s) | Count | Verdict |
|---|---|---|---|
| Coffee shops | `amenity=cafe` (281) + `shop=coffee` (7) | **288** | ✅ Plenty — but `amenity=cafe` is inflated by Belgian bars (see §3) |
| Bakeries | `shop=bakery` | **137** | ✅ Plenty |
| Confectioneries | `shop=pastry` (19) + `shop=confectionery` (14) | **33** | ⚠️ Thin but workable — merge the two tags into one type |
| Vegan spots | `diet:vegan=yes` (43) + `=only` (5) | **48** | ✅ Lens GO (≥30) — but flag the undercount (see §4) |

---

## 2. OSM / Overpass counts

**Boundary used:** `area["name"="Antwerpen"]["admin_level"="8"]` — resolved to exactly **1** relation (the City of Antwerp municipality). `[VERIFIED]`

**Endpoint:** `https://overpass-api.de/api/interpreter` (POST `data=`), `[out:json]`, `out count;`

| # | What | Tag(s) | Count | Notes |
|---|---|---|---|---|
| 1 | Cafés | `amenity=cafe` (node+way) | **281** | Includes bars/pubs (BE tagging, §3) |
| 2 | Coffee shops | `shop=coffee` (node+way) | **7** | Beans/coffee retail; small |
| 3 | Cafés flagged bar-ish | `amenity=cafe` + (`bar=yes`/`microbrewery=yes`/`real_ale=yes`) | **2** | Explicit alcohol tags barely used → under-detects |
| 4 | Bakeries | `shop=bakery` (node+way) | **137** | Solid |
| 5 | Pastry | `shop=pastry` (node+way) | **19** | |
| 6 | Confectionery | `shop=confectionery` (node+way) | **14** | Combine with pastry → 33 |
| 7 | Vegan (yes) | `diet:vegan=yes` | **43** | |
| 8 | Vegan (only) | `diet:vegan=only` | **5** | Fully vegan venues |
| 9 | Vegetarian | `diet:vegetarian~yes\|only` | **103** | Optional broader lens |
| 10 | Train stations | `railway=station` (node+way) | **20** | Attractor |
| 11 | Transit nodes | `public_transport=*` (node) | **1578** | Strong `transit` signal coverage |
| 12 | Offices | `office=*` (nwr) | **445** | Attractor |
| 13 | Universities | `amenity=university` (nwr) | **30** | Attractor |
| 14 | All shops | `shop=*` (nwr) | **2810** | Retail footfall proxy base |

> Two queries hit a transient `504 Gateway Timeout` on the first attempt and succeeded on retry (`shop=coffee`, `diet:vegetarian`) — counts above are the successful values.

### Raw Overpass queries used

```overpassql
# pattern (one per row); AREA = area["name"="Antwerpen"]["admin_level"="8"]->.a;
[out:json][timeout:90]; {AREA} (node["amenity"="cafe"](area.a);way["amenity"="cafe"](area.a);); out count;
[out:json][timeout:90]; {AREA} (node["shop"="coffee"](area.a);way["shop"="coffee"](area.a);); out count;
[out:json][timeout:90]; {AREA} (nwr["amenity"="cafe"]["bar"="yes"](area.a);nwr["amenity"="cafe"]["microbrewery"="yes"](area.a);nwr["amenity"="cafe"]["real_ale"="yes"](area.a);); out count;
[out:json][timeout:90]; {AREA} (node["shop"="bakery"](area.a);way["shop"="bakery"](area.a);); out count;
[out:json][timeout:90]; {AREA} (node["shop"="pastry"](area.a);way["shop"="pastry"](area.a);); out count;
[out:json][timeout:90]; {AREA} (node["shop"="confectionery"](area.a);way["shop"="confectionery"](area.a);); out count;
[out:json][timeout:90]; {AREA} (nwr["diet:vegan"="yes"](area.a);); out count;
[out:json][timeout:90]; {AREA} (nwr["diet:vegan"="only"](area.a);); out count;
[out:json][timeout:90]; {AREA} (nwr["diet:vegetarian"~"yes|only"](area.a);); out count;
[out:json][timeout:90]; {AREA} (node["railway"="station"](area.a);way["railway"="station"](area.a);); out count;
[out:json][timeout:90]; {AREA} (node["public_transport"](area.a);); out count;
[out:json][timeout:90]; {AREA} (nwr["office"](area.a);); out count;
[out:json][timeout:90]; {AREA} (nwr["amenity"="university"](area.a);); out count;
[out:json][timeout:90]; {AREA} (nwr["shop"](area.a);); out count;
```

---

## 3. Café–bar contamination estimate + recommended filter

**Confirmed concern, but not measurable via explicit tags.** In Belgium `amenity=cafe` is routinely mapped onto bars/pubs. Yet only **2 of 281** cafés carry an explicit alcohol tag (`bar=yes`/`microbrewery`/`real_ale`). So the founding-doc filter (drop those tags) removes ~0.7% — it is a **floor, not a fix**.

**Recommendation:**
- Apply the explicit-alcohol filter anyway (cheap, removes obvious bars).
- Treat the resulting café count as an **upper bound** and say so honestly in the UI/README (consistent with the "signals, not guarantees" framing).
- Optional stronger signal (later): also drop `amenity=cafe` co-tagged with `amenity=bar`/`pub`, or those whose `name` matches a bar/pub/brouwerij/taverne pattern. Do NOT over-engineer for Phase 0.
- `shop=coffee` (7) is clean coffee retail — keep, but it barely moves the needle.

---

## 4. Vegan lens viability verdict

**GO.** `diet:vegan` total = **48** (43 `yes` + 5 `only`), above the ~30 threshold for a meaningful coverage layer.

**Caveats to surface (UI + README):**
- The `diet:vegan` tag **systematically undercounts** — many venues with vegan options aren't tagged. "Gap" = *no documented vegan offering*, not *no vegan food*.
- Keep it as a **post-processor lens** over base opportunity (`opp * (1 - vegan_coverage)`), never a standalone business type — there is no open data for where vegan demand lives.
- `diet:vegetarian` (103) is available if a broader "plant-forward" lens is ever wanted; not needed now.

---

## 5. Statbel datasets

All download URLs `[VERIFIED]` live via `curl -sIL` (HTTP 200). Join-key column name is `[UNVERIFIED]` against file contents — stated from Statbel convention; confirm against the linked "Columns description" files.

| Dataset | Page | Direct URL | HTTP | Size | Most recent | Join key | CRS |
|---|---|---|---|---|---|---|---|
| Statistical sectors **geometry** | [2022 page](https://statbel.fgov.be/en/open-data/statistical-sectors-2022) | `.../Statistische%20sectoren/sh_statbel_statistical_sectors_31370_20220101.shp.zip` (also `.geojson.zip`, `.sqlite.zip`) | 200 | 31.9 MB shp / 45.5 MB geojson | 2022 vintage (2020–2024 versions exist) | `CD_SECTOR` (conv.) | **EPSG:31370** (Lambert 72); 3812 also offered |
| **Fiscal income** by sector | [income page](https://statbel.fgov.be/en/open-data/fiscal-statistics-income-statistical-sector) | `.../arbeid%20per%20sector/TF_PSNL_INC_TAX_SECTOR.xlsx` | 200 | 22.7 MB | **income year 2023** (series 2005–2023) | `CD_SECTOR` (conv.) | n/a (tabular) |
| **Population** by sector | [population 2024](https://statbel.fgov.be/en/open-data/population-statistical-sector-2024) | `.../bevolking/sectoren/OPENDATA_SECTOREN_2024.xlsx` | 200 | 1.5 MB | **2024** | `CD_SECTOR` (conv.) | n/a (tabular) |

**Column-description helper files (verified downloadable):**
- Sectors: `https://statbel.fgov.be/sites/default/files/files/opendata/Statistische%20sectoren/Columns%20description_0.xlsx` (200, 18 KB)
- Income variables: `https://statbel.fgov.be/sites/default/files/files/opendata/arbeid%20per%20sector/fiscales_variables_vers2.xlsx`
- Population columns: `https://statbel.fgov.be/sites/default/files/files/opendata/bevolking/sectoren/Columns%20description2020.xlsx`

**Year compatibility:** geometry (2022) ↔ income (2023) ↔ population (2024) are different vintages, but the **sector code is stable** across them, so merge loss should be small. For tightest alignment, use the sector-geometry vintage closest to the data years (a 2023/2024 geometry version likely exists on the matching Statbel page). **Caveat:** since 2019-01-01 the municipality (NIS) code is **no longer derivable** from the sector code — join municipality separately via `CD_REFNIS` if needed, and log the unmatched share after each merge.

---

## 6. Recommendations

1. **Keep cafés + bakeries** — rich data (288 / 137).
2. **Merge `shop=pastry` + `shop=confectionery`** into one `confectionery` type (33 combined). It's thin → percentile normalization is noisier; consider a slightly coarser H3 res or wider neighbor smoothing for this type only, and label it as lower-confidence.
3. **Café count is an upper bound** — apply the explicit-alcohol filter, but state honestly it under-detects Belgian café-bars.
4. **Vegan lens: GO** (48 tagged), shipped as a post-processor with a visible "documented coverage, tag undercounts" note.
5. **Attractors are well-covered** — `public_transport` (1578) and `shop=*` (2810) give a strong `traffic`/`transit` proxy base; `office` (445) + `university` (30) feed the office signal.
6. **Statbel:** download the **EPSG:31370 shapefile** (smaller than geojson), `to_crs(4326)` immediately, clip to the Antwerp municipality early to keep the ~20k-sector file light; join income + population by `CD_SECTOR` (confirm exact column via the description files); log unmatched share.
7. **Pipeline config:** the placeholder URLs in `pipeline/config.py` should be replaced with the four verified URLs above.

### Data risks for the pipeline
- Confectionery sample is small (33) → noisy opportunity scores for that type.
- Café count inflated by bars and not reliably correctable → honest "upper bound" framing.
- `diet:vegan` undercounts → lens is directional only.
- Sector-vintage mismatch across the 3 Statbel files → expect a small unmatched share; log it.
- Large geometry download (32–45 MB) → clip to Antwerp before any spatial ops.

---

*Recon method: OSM counts via direct Overpass `out count;` queries (Python `urllib`, polite spacing + retry); Statbel via official `statbel.fgov.be` open-data pages with direct-URL liveness checks (`curl -sIL`). No application code written in this phase.*
