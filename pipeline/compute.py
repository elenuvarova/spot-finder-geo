"""Stage 5: compute opportunity scores and write the final GeoJSON.

Orchestration:
  1. Load the aggregated grid (build_grid.py output) and the cleaned points
     (for vegan_coverage).
  2. Normalise the drivers to 0..1 ACROSS all hexes (traffic_norm, transit_norm,
     residential_norm, income_norm) plus per-type gap_norm_<type>.
  3. For each type, apply its distinct formula (formulas.py) to get a RAW score.
  4. Percentile-normalise RAW to opp_<type> in 0..1 WITHIN that type.
  5. Null out opp_<type> for hexes with n_food < NOISE_MIN_FOOD.
  6. Compute vegan_coverage (vegan-tagged / total establishments in hex).
  7. Write backend/data/antwerpen.geojson with EXACTLY the schema contract.

Run:  python pipeline/compute.py
Inputs:  pipeline/data/grid.geojson, pipeline/data/osm_points_clean.geojson
Output:  backend/data/antwerpen.geojson
"""

import json
import os

import geopandas as gpd
import h3
import numpy as np
import pandas as pd

import config
from formulas import FORMULA_REGISTRY

# h3 v3/v4 shim for the point->cell assignment used by vegan_coverage.
if hasattr(h3, "latlng_to_cell"):
    _latlng_to_cell = h3.latlng_to_cell
else:
    _latlng_to_cell = h3.geo_to_h3


def _minmax_norm(series):
    """Min-max normalise a numeric series to 0..1 across all hexes.

    A constant column (max == min) normalises to all-zeros, which is the
    neutral choice: a driver that never varies adds no signal.
    """
    s = pd.to_numeric(series, errors="coerce").fillna(0.0).astype(float)
    lo = s.min()
    hi = s.max()
    if hi <= lo:
        return pd.Series(np.zeros(len(s)), index=s.index)
    return (s - lo) / (hi - lo)


def _gap_norm(series):
    """Normalise a gap (metres-to-nearest) to 0..1 where a BIGGER gap -> ~1.

    Bigger gap = more underserved = higher opportunity, so this is a plain
    min-max where the largest gap maps to 1 and the smallest to 0.
    """
    return _minmax_norm(series)


def _percentile_within_type(raw):
    """Percentile-rank a RAW score series within the type, scaled to 0..1.

    Uses the average-rank percentile so ties share a rank. With n hexes the
    result spans (>0..1]; we rescale so the minimum maps to 0 and the maximum
    to 1, giving a clean 0..1 within-type spread. NaN rows (excluded hexes)
    stay NaN and are handled by the caller.
    """
    s = pd.to_numeric(raw, errors="coerce")
    valid = s.dropna()
    out = pd.Series(np.nan, index=s.index, dtype=float)
    if len(valid) == 0:
        return out
    if len(valid) == 1:
        out.loc[valid.index] = 1.0
        return out
    # Average-rank percentile in (0,1].
    pct = valid.rank(method="average", pct=True)
    # Rescale to span exactly [0,1] within the valid set.
    lo, hi = pct.min(), pct.max()
    if hi > lo:
        pct = (pct - lo) / (hi - lo)
    else:
        pct = pct * 0.0  # all equal -> all 0
    out.loc[valid.index] = pct.astype(float)
    return out


def _compute_vegan_coverage(grid):
    """Return a per-hex Series: vegan-tagged / total food establishments.

    Counts are taken from the cleaned points assigned to each hex at the grid
    resolution. Hexes with zero food establishments get 0.0 coverage.
    The diet:vegan tag undercounts reality, so this is a DOCUMENTED-coverage
    signal, not the true vegan share.
    """
    with open(config.CLEAN_POINTS_PATH, "r", encoding="utf-8") as fh:
        fc = json.load(fh)

    res = config.H3_RESOLUTION
    total = {}
    vegan = {}
    for feat in fc.get("features", []):
        p = feat["properties"]
        if not p.get("is_food"):
            continue
        lon, lat = feat["geometry"]["coordinates"]
        h = _latlng_to_cell(lat, lon, res)
        total[h] = total.get(h, 0) + 1
        if p.get("vegan"):
            vegan[h] = vegan.get(h, 0) + 1

    cov = []
    for h in grid["h3"]:
        t = total.get(h, 0)
        v = vegan.get(h, 0)
        cov.append((v / t) if t > 0 else 0.0)
    return pd.Series(cov, index=grid.index, dtype=float)


def compute():
    """Run the scoring orchestration and write the final GeoJSON."""
    grid = gpd.read_file(config.GRID_PATH)
    if grid.crs is None:
        grid = grid.set_crs(config.OUTPUT_CRS)
    elif str(grid.crs).upper() != "EPSG:4326":
        grid = grid.to_crs(config.OUTPUT_CRS)

    print(f"[compute] loaded {len(grid)} hexes")

    # --- 2. normalise drivers 0..1 across all hexes ------------------------
    grid["traffic_norm"] = _minmax_norm(grid["traffic"])
    grid["transit_norm"] = _minmax_norm(grid["transit"])
    grid["residential_norm"] = _minmax_norm(grid["residential"])
    grid["income_norm"] = _minmax_norm(grid["income"])

    # Per-type gap normalisation (bigger gap -> closer to 1).
    for t in config.TYPES:
        grid[f"gap_norm_{t}"] = _gap_norm(grid[f"gap_{t}"])

    # --- 3 & 4. per-type RAW formula -> within-type percentile opp ---------
    for t in config.TYPES:
        formula = FORMULA_REGISTRY[t]
        raw = grid.apply(lambda r: formula(r), axis=1).astype(float)

        # --- 5. noise floor: exclude sparse hexes BEFORE percentile-ranking.
        # Hexes below the food threshold are nulled; ranking the remainder
        # keeps the within-type 0..1 spread honest (sparse hexes don't dilute
        # the distribution).
        mask_sparse = grid["n_food"] < config.NOISE_MIN_FOOD
        raw_scored = raw.copy()
        raw_scored[mask_sparse] = np.nan

        opp = _percentile_within_type(raw_scored)
        grid[f"opp_{t}"] = opp  # NaN where excluded / sparse

    # --- 6. vegan coverage -------------------------------------------------
    grid["vegan_coverage"] = _compute_vegan_coverage(grid)

    # --- 7. assemble GeoJSON with EXACTLY the schema contract --------------
    _write_geojson(grid)
    return config.OUTPUT_GEOJSON_PATH


def _num(x):
    """Round a float for compact output; pass ints through."""
    if x is None:
        return None
    f = float(x)
    if not np.isfinite(f):
        return None
    return round(f, 6)


def _opp_value(x):
    """opp_<type> serialiser: JSON null for NaN, else rounded 0..1 float."""
    if x is None:
        return None
    f = float(x)
    if not np.isfinite(f):
        return None
    return round(f, 6)


def _write_geojson(grid):
    """Serialise the grid to the exact GeoJSON contract and write to disk."""
    features = []
    for _, r in grid.iterrows():
        geom = r.geometry
        # Polygon coordinates as [[ [lon,lat], ... ]] in WGS84.
        coords = [list(map(list, geom.exterior.coords))]

        opp_cafe = r["opp_cafe"]
        opp_bakery = r["opp_bakery"]
        opp_conf = r["opp_confectionery"]

        props = {
            "h3": str(r["h3"]),
            "traffic": _num(r["traffic"]),
            "transit": _num(r["transit"]),
            "offices": int(r["offices"]),
            "residential": _num(r["residential"]),
            "income": _num(r["income"]),
            "n_food": int(r["n_food"]),
            "traffic_norm": _num(r["traffic_norm"]),
            "transit_norm": _num(r["transit_norm"]),
            "residential_norm": _num(r["residential_norm"]),
            "income_norm": _num(r["income_norm"]),
            "comp_cafe": int(r["comp_cafe"]),
            "comp_bakery": int(r["comp_bakery"]),
            "comp_confectionery": int(r["comp_confectionery"]),
            "gap_cafe": _num(r["gap_cafe"]),
            "gap_bakery": _num(r["gap_bakery"]),
            "gap_confectionery": _num(r["gap_confectionery"]),
            "opp_cafe": _opp_value(opp_cafe),
            "opp_bakery": _opp_value(opp_bakery),
            "opp_confectionery": _opp_value(opp_conf),
            "vegan_coverage": _num(r["vegan_coverage"]),
        }
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": coords},
            "properties": props,
        })

    fc = {"type": "FeatureCollection", "features": features}
    os.makedirs(os.path.dirname(config.OUTPUT_GEOJSON_PATH), exist_ok=True)
    with open(config.OUTPUT_GEOJSON_PATH, "w", encoding="utf-8") as fh:
        json.dump(fc, fh, ensure_ascii=False)

    # Summary logging.
    n_scored = {t: int(grid[f"opp_{t}"].notna().sum()) for t in config.TYPES}
    print(f"[compute] hexes with scores per type: {n_scored}")
    print(f"[compute] wrote {len(features)} features -> {config.OUTPUT_GEOJSON_PATH}")


if __name__ == "__main__":
    compute()
