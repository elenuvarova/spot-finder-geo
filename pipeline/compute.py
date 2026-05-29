"""Stage 5: compute opportunity scores and write the final GeoJSON.

Orchestration:
  1. Load the aggregated grid (build_grid.py output) and the cleaned points
     (for the diet coverages).
  2. Normalise the drivers to 0..1 ACROSS all hexes (traffic_norm, transit_norm,
     residential_norm, income_norm) plus per-type gap_norm_<type>.
  3. For each type, apply its distinct formula (formulas.py) to get a RAW score.
  4. Percentile-normalise RAW to opp_<type> in 0..1 WITHIN that type.
  5. Null out opp_<type> unless the sector is scorable: neighbour-aware activity
     (n_food_area >= NOISE_MIN_FOOD) AND viable (residential > 0 OR n_food > 0),
     so uninhabitable river/port/pure-infra polygons are greyed out.
  6. Carry through the diet coverages (vegan/vegetarian/glutenfree/halal).
  7. Write backend/data/antwerpen.geojson with EXACTLY the schema contract.

Run:  python pipeline/compute.py
Inputs:  pipeline/data/grid.geojson, pipeline/data/osm_points_clean.geojson
Output:  backend/data/antwerpen.geojson
"""

import json
import os

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import mapping

import config
from formulas import FORMULA_REGISTRY


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


def compute():
    """Run the scoring orchestration and write the final GeoJSON."""
    grid = gpd.read_file(config.GRID_PATH)
    if grid.crs is None:
        grid = grid.set_crs(config.OUTPUT_CRS)
    elif str(grid.crs).upper() != "EPSG:4326":
        grid = grid.to_crs(config.OUTPUT_CRS)

    print(f"[compute] loaded {len(grid)} sectors")

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

        # --- 5. noise floor: exclude non-scorable sectors BEFORE percentile-ranking.
        # A sector is scored ONLY IF it clears BOTH conditions:
        #   (a) n_food_area >= NOISE_MIN_FOOD  — the NEIGHBOUR-AWARE activity gate
        #       (n_food_area = sector + touching neighbours), so an empty sector
        #       next to activity is still an underserved candidate; and
        #   (b) residential > 0 OR n_food > 0  — the sector is VIABLE: people live
        #       there OR it already hosts establishments of its own.
        # Condition (b) NULLs uninhabitable polygons (river / port / pure
        # infrastructure: 0 residents AND 0 establishments) even when a neighbour
        # has food — you cannot open a business on water or a railyard, so scoring
        # and colouring them red ("low opportunity") was misleading. Sectors with
        # residents or their own establishments stay scorable. Ranking the
        # remainder keeps the within-type 0..1 spread honest.
        viable = (grid["residential"] > 0) | (grid["n_food"] > 0)
        mask_keep = (grid["n_food_area"] >= config.NOISE_MIN_FOOD) & viable
        raw_scored = raw.copy()
        raw_scored[~mask_keep] = np.nan

        opp = _percentile_within_type(raw_scored)
        grid[f"opp_{t}"] = opp  # NaN where excluded / sparse

    # --- 6. diet coverages (already computed per sector in build_grid) -----
    # One coverage per diet lens; each UNDERCOUNTS reality (documented-coverage
    # signal, not demand/quality). Coerce numeric and floor missing to 0.
    for slug in config.DIET_LENSES:
        col = f"{slug}_coverage"
        grid[col] = pd.to_numeric(grid[col], errors="coerce").fillna(0.0)

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

        opp_cafe = r["opp_cafe"]
        opp_bakery = r["opp_bakery"]
        opp_conf = r["opp_confectionery"]

        props = {
            "unit_id": str(r["unit_id"]),
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
            "vegetarian_coverage": _num(r["vegetarian_coverage"]),
            "glutenfree_coverage": _num(r["glutenfree_coverage"]),
            "halal_coverage": _num(r["halal_coverage"]),
        }
        features.append({
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": props,
        })

    fc = {"type": "FeatureCollection", "features": features}
    os.makedirs(os.path.dirname(config.OUTPUT_GEOJSON_PATH), exist_ok=True)
    with open(config.OUTPUT_GEOJSON_PATH, "w", encoding="utf-8") as fh:
        json.dump(fc, fh, ensure_ascii=False)

    # Summary logging.
    n_scored = {t: int(grid[f"opp_{t}"].notna().sum()) for t in config.TYPES}
    print(f"[compute] sectors with scores per type: {n_scored}")
    print(f"[compute] wrote {len(features)} features -> {config.OUTPUT_GEOJSON_PATH}")


if __name__ == "__main__":
    compute()
