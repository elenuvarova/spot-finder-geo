"""Stage 4: build the H3 grid over Antwerp and aggregate the input pool.

For every H3 cell (resolution from config) whose centre falls in the Antwerp
bbox we compute the raw aggregates the formulas need:

  * traffic      honest foot-traffic PROXY = weighted gastro+retail points in
                 the hex AND its immediate neighbours (k-ring of 1).
  * transit      transit access score = transit stops in hex+neighbours.
  * offices      offices + universities count in the hex.
  * residential  population PROXY from intersecting Statbel sector(s)
                 (area-weighted by overlap).
  * income       avg fiscal income (EUR) from intersecting Statbel sector(s)
                 (population-weighted, falling back to area-weighted).
  * n_food       total food establishments whose point is inside the hex.
  * comp_<type>  competitors of that type in hex+neighbours.
  * gap_<type>   metres from the hex centre to the nearest establishment of
                 that type (anywhere in Antwerp).

It is purely geometric aggregation; normalisation and the scoring formulas
happen in compute.py.

Run:  python pipeline/build_grid.py
Inputs:  pipeline/data/osm_points_clean.geojson, pipeline/data/statbel_sectors.geojson
Output:  pipeline/data/grid.geojson
"""

import json
import math
import os

import geopandas as gpd
import h3
import pandas as pd
from shapely.geometry import Point, Polygon, box

import config

# ---------------------------------------------------------------------------
# h3 v3/v4 compatibility shim.
# The h3 Python API renamed functions between v3 and v4. We detect which is
# present so the pipeline runs against either installed major version.
# ---------------------------------------------------------------------------
if hasattr(h3, "latlng_to_cell"):  # h3 >= 4
    _latlng_to_cell = h3.latlng_to_cell
    _cell_to_latlng = h3.cell_to_latlng
    _cell_to_boundary = h3.cell_to_boundary
    _grid_disk = h3.grid_disk
    _polygon_to_cells = None  # handled below
    _LatLngPoly = getattr(h3, "LatLngPoly", None)
else:  # h3 v3
    _latlng_to_cell = h3.geo_to_h3
    _cell_to_latlng = h3.h3_to_geo
    _cell_to_boundary = h3.h3_to_geo_boundary
    _grid_disk = h3.k_ring
    _polygon_to_cells = h3.polyfill
    _LatLngPoly = None


def _hex_boundary_lonlat(h):
    """Return the hex boundary as a list of (lon, lat) pairs for a Polygon.

    h3 returns boundaries as (lat, lng). The GeoJSON contract is (lon, lat),
    so we swap. We close the ring explicitly.
    """
    boundary = _cell_to_boundary(h)
    # h3 v4 returns list of (lat, lng); v3 default also (lat, lng).
    ring = [(lng, lat) for (lat, lng) in boundary]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def _cells_covering_bbox():
    """Return the set of H3 cells whose centre lies within the Antwerp bbox.

    We polyfill the bbox polygon and then keep only cells whose centre is
    actually inside the bbox (polyfill on some versions includes boundary
    cells whose centre is just outside).
    """
    s, w, n, e = config.ANTWERP_BBOX
    res = config.H3_RESOLUTION

    if hasattr(h3, "geo_to_cells"):
        # Not all builds expose this; prefer explicit polygon fill below.
        pass

    if _LatLngPoly is not None and hasattr(h3, "polygon_to_cells"):
        # h3 v4: outer ring as list of (lat, lng).
        ring = [(s, w), (s, e), (n, e), (n, w), (s, w)]
        poly = _LatLngPoly(ring)
        cells = set(h3.polygon_to_cells(poly, res))
    else:
        # h3 v3 polyfill expects a GeoJSON-like dict with (lng, lat) coords.
        geojson_poly = {
            "type": "Polygon",
            "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
        }
        cells = set(_polygon_to_cells(geojson_poly, res, geo_json_conformant=True))

    # Keep only cells whose centre is inside the bbox.
    kept = set()
    for c in cells:
        lat, lng = _cell_to_latlng(c)
        if s <= lat <= n and w <= lng <= e:
            kept.add(c)
    return kept


def _neighbors(h):
    """Hex plus its first ring of neighbours (k-ring of 1)."""
    return set(_grid_disk(h, 1))


def _load_points():
    """Load cleaned points into a GeoDataFrame in WGS84."""
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
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=config.OUTPUT_CRS)
    return gdf


def _load_sectors():
    """Load Statbel sectors (already WGS84) as a GeoDataFrame."""
    sectors = gpd.read_file(config.STATBEL_SECTORS_PATH)
    if sectors.crs is None:
        sectors = sectors.set_crs(config.OUTPUT_CRS)
    elif str(sectors.crs).upper() not in ("EPSG:4326",):
        sectors = sectors.to_crs(config.OUTPUT_CRS)
    return sectors


def _haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres between two WGS84 points."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


# A safe "no establishment found" gap value: bigger than any intra-Antwerp
# distance, so an empty type still produces a finite, normalisable number.
GAP_FALLBACK_M = 50000.0


def build_grid():
    """Build the grid and write per-hex aggregates as GeoJSON."""
    points = _load_points()
    sectors = _load_sectors()

    cells = _cells_covering_bbox()
    print(f"[build_grid] H3 res {config.H3_RESOLUTION}: {len(cells)} cells over Antwerp")

    # Assign every point to the H3 cell containing it (res level).
    res = config.H3_RESOLUTION
    points = points.copy()
    points["h3"] = [
        _latlng_to_cell(lat, lon, res)
        for lat, lon in zip(points["lat"], points["lon"])
    ]

    # Pre-bucket per-cell point indices for fast hex+neighbour aggregation.
    by_cell = {}
    for idx, h in zip(points.index, points["h3"]):
        by_cell.setdefault(h, []).append(idx)

    # Per-type coordinate arrays for nearest-distance (gap) computation.
    type_coords = {t: [] for t in config.TYPES}
    for _, row in points.iterrows():
        if row["spot_type"] in type_coords:
            type_coords[row["spot_type"]].append((row["lat"], row["lon"]))

    # Build a spatial index on sectors for the residential/income join.
    sectors_sindex = sectors.sindex

    records = []
    for h in cells:
        ring = _neighbors(h)
        # Collect point indices in hex + neighbours.
        ring_idx = []
        for c in ring:
            ring_idx.extend(by_cell.get(c, []))
        hex_idx = by_cell.get(h, [])

        ring_pts = points.loc[ring_idx] if ring_idx else points.iloc[0:0]
        hex_pts = points.loc[hex_idx] if hex_idx else points.iloc[0:0]

        # --- traffic PROXY: weighted gastro+retail in hex+neighbours --------
        n_gastro = int(ring_pts["is_gastro"].sum()) if len(ring_pts) else 0
        n_retail = int(ring_pts["is_retail"].sum()) if len(ring_pts) else 0
        traffic = (config.TRAFFIC_PROXY_WEIGHTS["gastro"] * n_gastro
                   + config.TRAFFIC_PROXY_WEIGHTS["retail"] * n_retail)

        # --- transit: stops in hex+neighbours -------------------------------
        transit = int(ring_pts["is_transit"].sum()) if len(ring_pts) else 0

        # --- offices: offices + universities IN the hex ---------------------
        offices = int(hex_pts["is_office"].sum()) if len(hex_pts) else 0

        # --- n_food: food establishments IN the hex -------------------------
        n_food = int(hex_pts["is_food"].sum()) if len(hex_pts) else 0

        # --- per-type competitors in hex+neighbours -------------------------
        comp = {}
        for t in config.TYPES:
            comp[t] = (int((ring_pts["spot_type"] == t).sum())
                       if len(ring_pts) else 0)

        # --- residential + income from intersecting Statbel sector(s) -------
        clat, clng = _cell_to_latlng(h)
        hex_poly = Polygon(_hex_boundary_lonlat(h))
        residential, income = _sector_values(hex_poly, sectors, sectors_sindex)

        # --- per-type gap: metres to nearest establishment of that type -----
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

        records.append({
            "h3": h,
            "geometry": Polygon(_hex_boundary_lonlat(h)),
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
        })

    grid = gpd.GeoDataFrame(records, geometry="geometry", crs=config.OUTPUT_CRS)
    os.makedirs(config.DATA_DIR, exist_ok=True)
    grid.to_file(config.GRID_PATH, driver="GeoJSON")
    print(f"[build_grid] wrote {len(grid)} hexes -> {config.GRID_PATH}")
    return config.GRID_PATH


def _sector_values(hex_poly, sectors, sindex):
    """Return (residential_proxy, income) for a hex from intersecting sectors.

    Population is summed across intersecting sectors, area-weighted by the
    share of each sector that overlaps the hex (so a hex straddling two
    sectors gets a fair slice of each sector's population).

    Income is the population-weighted mean across the same sectors (falling
    back to area-weighted mean when population is missing/zero).
    """
    try:
        candidate_pos = list(sindex.intersection(hex_poly.bounds))
    except Exception:
        candidate_pos = list(range(len(sectors)))
    if not candidate_pos:
        return 0.0, 0.0

    candidates = sectors.iloc[candidate_pos]
    pop_field = config.STATBEL_POPULATION_FIELD
    inc_field = config.STATBEL_INCOME_FIELD

    residential = 0.0
    inc_weight_sum = 0.0          # sum of weights used for income mean
    inc_weighted_val = 0.0
    area_weight_sum = 0.0
    area_weighted_inc = 0.0

    for _, sec in candidates.iterrows():
        geom = sec.geometry
        if geom is None or not geom.intersects(hex_poly):
            continue
        inter = geom.intersection(hex_poly)
        if inter.is_empty:
            continue
        sec_area = geom.area
        if sec_area <= 0:
            continue
        share = inter.area / sec_area  # 0..1 of the sector inside this hex

        pop = sec.get(pop_field)
        inc = sec.get(inc_field)
        pop = float(pop) if pop is not None and not _isnan(pop) else 0.0
        has_inc = inc is not None and not _isnan(inc)

        # Population proxy: this hex's share of the sector's residents.
        residential += pop * share

        if has_inc:
            inc = float(inc)
            # Population-weighted income mean (this hex's slice of residents).
            w = pop * share
            inc_weight_sum += w
            inc_weighted_val += inc * w
            # Area-weighted fallback.
            area_weight_sum += share
            area_weighted_inc += inc * share

    if inc_weight_sum > 0:
        income = inc_weighted_val / inc_weight_sum
    elif area_weight_sum > 0:
        income = area_weighted_inc / area_weight_sum
    else:
        income = 0.0

    return residential, income


def _isnan(x):
    try:
        return math.isnan(float(x))
    except (TypeError, ValueError):
        return True


if __name__ == "__main__":
    build_grid()
