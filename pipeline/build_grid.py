"""Stage 4: aggregate the input pool onto Statbel statistical sectors.

Each spatial unit is a REAL Antwerp statistical sector (Statbel), not an
arbitrary grid cell — so income/population are native (no resampling) and the
map is always "filled" rather than a sparse grid. For every sector we compute
the raw aggregates the formulas need:

  * traffic        foot-traffic PROXY = weighted gastro+retail points in sector
  * transit        transit stops in the sector
  * offices        offices + universities in the sector
  * residential    sector population (native Statbel POPULATION)
  * income         sector mean fiscal income (native Statbel MEAN_INCOME)
  * n_food         scored-type food establishments in the sector
  * comp_<type>    competitors of that type in the sector
  * gap_<type>     metres from the sector's representative point to the nearest
                   establishment of that type (anywhere in Antwerp)
  * vegan_coverage vegan-tagged / total food establishments in the sector

Normalisation and the scoring formulas happen in compute.py.

Run:  python pipeline/build_grid.py
Inputs:  pipeline/data/osm_points_clean.geojson, pipeline/data/statbel_sectors.geojson
Output:  pipeline/data/grid.geojson  (one feature per sector)
"""

import json
import math
import os

import geopandas as gpd
from shapely.geometry import Point

import config

# A safe "no establishment found" gap: bigger than any intra-Antwerp distance,
# so an empty type still yields a finite, normalisable number.
GAP_FALLBACK_M = 50000.0


def _load_points():
    """Load cleaned establishment points into a WGS84 GeoDataFrame."""
    with open(config.CLEAN_POINTS_PATH, "r", encoding="utf-8") as fh:
        fc = json.load(fh)
    rows = []
    for feat in fc.get("features", []):
        lon, lat = feat["geometry"]["coordinates"]
        p = feat["properties"]
        rows.append({
            "lon": lon, "lat": lat,
            "spot_type": p.get("spot_type"),
            "is_food": bool(p.get("is_food")),
            "is_gastro": bool(p.get("is_gastro")),
            "is_retail": bool(p.get("is_retail")),
            "is_transit": bool(p.get("is_transit")),
            "is_office": bool(p.get("is_office")),
            "vegan": bool(p.get("vegan")),
            "geometry": Point(lon, lat),
        })
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=config.OUTPUT_CRS)


def _load_sectors():
    """Load Statbel sectors (polygons + population + income) in WGS84."""
    sectors = gpd.read_file(config.STATBEL_SECTORS_PATH)
    if sectors.crs is None:
        sectors = sectors.set_crs(config.OUTPUT_CRS)
    elif str(sectors.crs).upper() != "EPSG:4326":
        sectors = sectors.to_crs(config.OUTPUT_CRS)
    return sectors.reset_index(drop=True)


def _haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres between two WGS84 points."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def _isnan(x):
    try:
        return math.isnan(float(x))
    except (TypeError, ValueError):
        return True


def build_grid():
    """Aggregate points onto sectors and write per-sector aggregates as GeoJSON."""
    points = _load_points()
    sectors = _load_sectors()
    print(f"[build_grid] {len(sectors)} Statbel sectors, {len(points)} points")

    code_f = config.STATBEL_SECTOR_CODE_FIELD
    pop_f = config.STATBEL_POPULATION_FIELD
    inc_f = config.STATBEL_INCOME_FIELD

    # Assign each establishment point to the sector that contains it.
    joined = gpd.sjoin(
        points, sectors[[code_f, "geometry"]], how="inner", predicate="within"
    )
    by_sector = {code: grp for code, grp in joined.groupby(code_f)}

    # Per-type coordinate arrays for nearest-distance (gap) computation.
    type_coords = {t: [] for t in config.TYPES}
    for lat, lon, st in zip(points["lat"], points["lon"], points["spot_type"]):
        if st in type_coords:
            type_coords[st].append((lat, lon))

    records = []
    for _, sec in sectors.iterrows():
        code = sec[code_f]
        grp = by_sector.get(code)

        if grp is None or len(grp) == 0:
            n_gastro = n_retail = transit = offices = n_food = n_vegan = n_eatery = 0
            comp = {t: 0 for t in config.TYPES}
        else:
            n_gastro = int(grp["is_gastro"].sum())
            n_retail = int(grp["is_retail"].sum())
            transit = int(grp["is_transit"].sum())
            offices = int(grp["is_office"].sum())
            n_food = int(grp["is_food"].sum())
            # Vegan coverage base = EATERIES (scored food types + gastro
            # attractors like restaurants/fast_food), so vegan restaurants count.
            eatery = grp["is_food"] | grp["is_gastro"]
            n_eatery = int(eatery.sum())
            n_vegan = int((eatery & grp["vegan"]).sum())
            comp = {t: int((grp["spot_type"] == t).sum()) for t in config.TYPES}

        traffic = (config.TRAFFIC_PROXY_WEIGHTS["gastro"] * n_gastro
                   + config.TRAFFIC_PROXY_WEIGHTS["retail"] * n_retail)

        pop = sec.get(pop_f)
        inc = sec.get(inc_f)
        residential = 0.0 if (pop is None or _isnan(pop)) else float(pop)
        income = 0.0 if (inc is None or _isnan(inc)) else float(inc)

        # Representative point is guaranteed inside the (possibly multi-)polygon.
        rp = sec.geometry.representative_point()
        clng, clat = rp.x, rp.y
        gap = {}
        for t in config.TYPES:
            coords = type_coords[t]
            if not coords:
                gap[t] = GAP_FALLBACK_M
                continue
            best = GAP_FALLBACK_M
            for (plat, plon) in coords:
                d = _haversine_m(clat, clng, plat, plon)
                if d < best:
                    best = d
            gap[t] = best

        # Low-n floor: a single venue (1/1) must not read as 100% coverage, so
        # only compute coverage once at least 3 eateries are documented here.
        vegan_coverage = (n_vegan / n_eatery) if n_eatery >= 3 else 0.0

        records.append({
            "unit_id": str(code),
            "geometry": sec.geometry,
            "traffic": float(traffic),
            "transit": float(transit),
            "offices": int(offices),
            "residential": float(residential),
            "income": float(income),
            "n_food": int(n_food),
            "comp_cafe": int(comp["cafe"]),
            "comp_bakery": int(comp["bakery"]),
            "comp_confectionery": int(comp["confectionery"]),
            "gap_cafe": float(gap["cafe"]),
            "gap_bakery": float(gap["bakery"]),
            "gap_confectionery": float(gap["confectionery"]),
            "vegan_coverage": float(vegan_coverage),
        })

    grid = gpd.GeoDataFrame(
        records, geometry="geometry", crs=config.OUTPUT_CRS
    ).reset_index(drop=True)

    # Neighbour-aware food count = a sector PLUS its touching neighbours. This is
    # the NOISE GATE basis (compute.py): a sector next to activity but with no
    # establishment of a type *itself* is exactly an underserved candidate, so we
    # score it rather than grey it out. `n_food` (per sector) stays the displayed
    # value; `n_food_area` is gating-only and is NOT written to the final GeoJSON.
    sidx = grid.sindex
    nf = grid["n_food"].to_numpy()
    area = []
    for geom in grid.geometry:
        nbrs = list(sidx.query(geom, predicate="intersects"))  # includes self
        area.append(int(nf[nbrs].sum()) if len(nbrs) else 0)
    grid["n_food_area"] = area

    os.makedirs(config.DATA_DIR, exist_ok=True)
    grid.to_file(config.GRID_PATH, driver="GeoJSON")
    n_scorable = int((grid["n_food_area"] >= config.NOISE_MIN_FOOD).sum())
    print(f"[build_grid] wrote {len(grid)} sectors -> {config.GRID_PATH} "
          f"({n_scorable} scorable: n_food_area >= {config.NOISE_MIN_FOOD})")
    return config.GRID_PATH


if __name__ == "__main__":
    build_grid()
