#!/usr/bin/env python3
"""Synthetic sample dataset generator for SpotFinder.

Produces a WGS84 / EPSG:4326 FeatureCollection of ~60 pointy-top hexagon cells
tiling a bounding box around Antwerp, carrying the FULL property schema the real
pipeline emits (see the GeoJSON CONTRACT in the project docs).

This is SYNTHETIC data so the backend and frontend can be developed and tested
without running the real OSM/Statbel pipeline. The committed
`backend/data/*.geojson` is REAL data, so this script is a convenience only; it
writes to `backend/data/sample.geojson` by default (override with --out) and
will NOT clobber a real city file.

DRY / single-source-of-truth: the scoring math is NOT reimplemented here. The
per-type opportunity formulas come from `formulas.FORMULA_REGISTRY`, the
within-type percentile ranking from `compute._percentile_within_type`, and the
driver/gap normalisation from `compute._minmax_norm` / `compute._gap_norm`, so
the sample and the real pipeline can never silently drift apart. The
neighbour-aware noise/viability gate also matches `compute.compute()` exactly.

Honest framing reminder for downstream copy: traffic is a PROXY (signals, not
guarantees) and the diet coverages reflect the documented diet:* tags, which
undercount reality. The numbers here are plausible but invented.

Run:  python pipeline/make_sample.py [--out backend/data/sample.geojson]
"""

import argparse
import json
import math
import os
import random

import pandas as pd

import compute
import config
from formulas import FORMULA_REGISTRY

# --- Bounding box around Antwerp (EPSG:4326) ---------------------------------
LON_MIN, LON_MAX = 4.36, 4.47
LAT_MIN, LAT_MAX = 51.17, 51.25

# Hex geometry. Pointy-top hexagons with a circumradius of ~0.007 deg.
# For a pointy-top hex with circumradius R:
#   width  = sqrt(3) * R      (flat side to flat side, horizontal)
#   height = 2 * R            (vertex to vertex, vertical)
# Rows are stacked with a vertical step of 3/4 * height and odd rows are
# offset horizontally by half a width, giving a non-overlapping tiling.
HEX_R = 0.007

# Approximate meters per degree at Antwerp's latitude (~51.21). Used only to
# convert gap distances (expressed in cell-radii) into meters for the contract.
LAT_MID = (LAT_MIN + LAT_MAX) / 2.0
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT_MID))

# Default output: a NON-city filename so a stray run never clobbers the real,
# committed backend/data/<city>.geojson the backend serves.
DEFAULT_OUT = os.path.join(config.REPO_ROOT, "backend", "data", "sample.geojson")


def hex_vertices(cx, cy, r):
    """Return the 6 vertices + closing vertex of a pointy-top hexagon.

    Pointy-top: a vertex points straight up, so vertex angles are offset by
    30 degrees from the horizontal. Vertices are emitted as [lon, lat] pairs
    with the first vertex repeated at the end to close the GeoJSON ring.
    """
    ring = []
    for i in range(6):
        angle = math.radians(60 * i - 30)  # -30 deg => pointy top
        vx = cx + r * math.cos(angle)
        vy = cy + r * math.sin(angle)
        ring.append([round(vx, 7), round(vy, 7)])
    ring.append(list(ring[0]))  # close the ring
    return ring


def build_centers():
    """Lay out hex cell centers covering the bounding box.

    Returns a list of (cx, cy) center coordinates. The grid is generated row by
    row; odd rows are shifted by half a cell width so the hexagons interlock.
    We aim for roughly 60 cells across the box.
    """
    width = math.sqrt(3) * HEX_R       # horizontal spacing within a row
    v_step = 1.5 * HEX_R               # vertical spacing between rows
    centers = []
    row = 0
    cy = LAT_MIN + HEX_R
    while cy <= LAT_MAX - HEX_R * 0.25:
        x_offset = (width / 2.0) if (row % 2 == 1) else 0.0
        cx = LON_MIN + HEX_R + x_offset
        while cx <= LON_MAX - width * 0.25:
            centers.append((round(cx, 7), round(cy, 7)))
            cx += width
        cy += v_step
        row += 1
    return centers


def haversine_m(lon1, lat1, lon2, lat2):
    """Great-circle distance in meters between two lon/lat points."""
    r_earth = 6_371_000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
    return 2 * r_earth * math.asin(math.sqrt(a))


def neighbors_within(centers, idx, radius):
    """Indices of cells whose centers lie within `radius` degrees of cell idx.

    Includes the cell itself. Used to aggregate gastro/retail points across a
    hex and its ring of neighbors for the traffic proxy and competitor counts,
    and to build the neighbour-aware n_food_area used by the noise gate.
    """
    cx, cy = centers[idx]
    out = []
    for j, (ox, oy) in enumerate(centers):
        if (ox - cx) ** 2 + (oy - cy) ** 2 <= radius ** 2:
            out.append(j)
    return out


def main(out_path=DEFAULT_OUT):
    random.seed(42)

    centers = build_centers()
    n = len(centers)

    # --- Raw per-cell signals -------------------------------------------------
    # Generate plausible raw values, then derive everything else.
    raw = []
    for i, (cx, cy) in enumerate(centers):
        # Distance from city-ish center skews some signals (more central =>
        # more traffic, offices, transit; outer => more residential).
        dx = (cx - (LON_MIN + LON_MAX) / 2) / (LON_MAX - LON_MIN)
        dy = (cy - (LAT_MIN + LAT_MAX) / 2) / (LAT_MAX - LAT_MIN)
        centrality = max(0.0, 1.0 - 2.0 * math.hypot(dx, dy))  # 1 center -> 0 edge

        transit = round(random.uniform(0.05, 0.9) * (0.4 + 0.6 * centrality), 4)
        offices = int(round(random.uniform(0, 30) * (0.2 + 0.8 * centrality)))
        residential = round(random.uniform(200, 6000) * (1.3 - 0.6 * centrality), 1)
        income = round(random.uniform(16000, 34000), 1)

        # A few cells get 0 residents to exercise the viability gate (an
        # uninhabitable river/port/infra sector: no residents AND no food).
        if random.random() < 0.08:
            residential = 0.0

        # Food establishments in the hex (small integers); some are 0 so the
        # neighbour-aware noise gate is exercised.
        n_food = random.choices(
            population=[0, 1, 2, 3, 4, 5, 6, 8, 11, 15],
            weights=[10, 12, 12, 11, 10, 9, 8, 7, 6, 5],
            k=1,
        )[0]
        n_food = int(round(n_food * (0.4 + 0.9 * centrality)))

        # Per-diet documented coverage seeds. Each diet:* tag undercounts
        # reality, so coverage is skewed low with plenty of zeros. Vegetarian
        # is the best-documented lens; halal/gluten-free the sparsest.
        def diet_seed(p_zero, scale):
            if random.random() < p_zero:
                return 0.0
            return round(min(random.random(), random.random()) * scale, 4)

        vegan = diet_seed(0.35, 0.45)
        vegetarian = diet_seed(0.25, 0.60)
        glutenfree = diet_seed(0.55, 0.35)
        halal = diet_seed(0.50, 0.40)

        # Per-cell point weight used to build the honest traffic proxy: a blend
        # of gastronomy + retail intensity. Scaled by centrality.
        point_weight = round(
            (random.uniform(0, 8) + n_food * 0.6) * (0.3 + 0.9 * centrality), 4
        )

        # Type competitor seeds within THIS hex (neighbors added later).
        comp_cafe_self = random.choices([0, 1, 2, 3], weights=[40, 30, 20, 10])[0]
        comp_bakery_self = random.choices([0, 1, 2], weights=[55, 30, 15])[0]
        comp_conf_self = random.choices([0, 1, 2], weights=[70, 22, 8])[0]

        raw.append({
            "cx": cx, "cy": cy,
            "transit": transit,
            "offices": offices,
            "residential": residential,
            "income": income,
            "n_food": n_food,
            "vegan": vegan,
            "vegetarian": vegetarian,
            "glutenfree": glutenfree,
            "halal": halal,
            "point_weight": point_weight,
            "comp_cafe_self": comp_cafe_self,
            "comp_bakery_self": comp_bakery_self,
            "comp_conf_self": comp_conf_self,
        })

    # Neighbor radius: 1.6x the row width catches the 6-neighbor ring.
    neigh_radius = math.sqrt(3) * HEX_R * 1.6
    neigh = [neighbors_within(centers, i, neigh_radius) for i in range(n)]

    # --- Traffic proxy: weighted gastro+retail points in hex + neighbors ------
    traffic = []
    comp_cafe = []
    comp_bakery = []
    comp_confectionery = []
    for i in range(n):
        t = 0.0
        cc = 0
        cb = 0
        cf = 0
        for j in neigh[i]:
            w = raw[j]["point_weight"]
            # Neighbors contribute at half weight; self at full weight.
            t += w if j == i else 0.5 * w
            cc += raw[j]["comp_cafe_self"]
            cb += raw[j]["comp_bakery_self"]
            cf += raw[j]["comp_conf_self"]
        traffic.append(round(t, 4))
        comp_cafe.append(cc)
        comp_bakery.append(cb)
        comp_confectionery.append(cf)

    transit = [raw[i]["transit"] for i in range(n)]
    residential = [raw[i]["residential"] for i in range(n)]
    income = [raw[i]["income"] for i in range(n)]
    n_food = [raw[i]["n_food"] for i in range(n)]

    # Neighbour-aware food count (sector + touching neighbours) = the noise-gate
    # basis, mirroring build_grid's n_food_area. n_food (per cell) stays the
    # displayed value; n_food_area is gating-only and never written out.
    n_food_area = [sum(n_food[j] for j in neigh[i]) for i in range(n)]

    # --- Gaps: meters to nearest establishment of each type -------------------
    # Cells that contain >=1 competitor of a type are "occupied"; gap is the
    # haversine distance from this cell center to the nearest occupied cell
    # center (0 if this cell itself is occupied). Larger gap => more whitespace.
    def gaps_for(comp_self_key):
        occupied = [i for i in range(n) if raw[i][comp_self_key] > 0]
        out = []
        for i in range(n):
            cx, cy = centers[i]
            if raw[i][comp_self_key] > 0:
                out.append(0.0)
                continue
            if not occupied:
                # No establishments anywhere: treat as a large but finite gap.
                out.append(round(HEX_R * M_PER_DEG_LAT * 12, 1))
                continue
            best = min(
                haversine_m(cx, cy, centers[j][0], centers[j][1])
                for j in occupied
            )
            out.append(round(best, 1))
        return out

    gap_cafe = gaps_for("comp_cafe_self")
    gap_bakery = gaps_for("comp_bakery_self")
    gap_confectionery = gaps_for("comp_conf_self")

    # --- Normalized drivers + gaps (reuse compute's helpers, no parallel copy)-
    traffic_norm = compute._minmax_norm(pd.Series(traffic)).tolist()
    transit_norm = compute._minmax_norm(pd.Series(transit)).tolist()
    residential_norm = compute._minmax_norm(pd.Series(residential)).tolist()
    income_norm = compute._minmax_norm(pd.Series(income)).tolist()

    # gap_norm_<type>: bigger gap maps closer to 1 (compute._gap_norm).
    gap_norm_cafe = compute._gap_norm(pd.Series(gap_cafe)).tolist()
    gap_norm_bakery = compute._gap_norm(pd.Series(gap_bakery)).tolist()
    gap_norm_confectionery = compute._gap_norm(pd.Series(gap_confectionery)).tolist()

    # --- Per-type RAW opportunity via the SHARED formula registry -------------
    # Build the row each formula expects (the *_norm drivers, comp_<type>, and
    # gap_norm_bakery) and apply FORMULA_REGISTRY[t]. No formula math lives here.
    rows = []
    for i in range(n):
        rows.append({
            "traffic_norm": traffic_norm[i],
            "transit_norm": transit_norm[i],
            "residential_norm": residential_norm[i],
            "income_norm": income_norm[i],
            "comp_cafe": comp_cafe[i],
            "comp_bakery": comp_bakery[i],
            "comp_confectionery": comp_confectionery[i],
            "gap_norm_cafe": gap_norm_cafe[i],
            "gap_norm_bakery": gap_norm_bakery[i],
            "gap_norm_confectionery": gap_norm_confectionery[i],
        })

    # --- Noise + viability gate (IDENTICAL to compute.compute()) --------------
    # Scored ONLY IF: n_food_area >= NOISE_MIN_FOOD (neighbour-aware activity)
    # AND (residential > 0 OR n_food > 0) (viable: people live there or it
    # already hosts establishments). Non-scorable cells are NaN -> JSON null.
    viable = [(residential[i] > 0) or (n_food[i] > 0) for i in range(n)]
    mask_keep = [
        (n_food_area[i] >= config.NOISE_MIN_FOOD) and viable[i]
        for i in range(n)
    ]

    opp = {}
    for t in config.TYPES:
        formula = FORMULA_REGISTRY[t]
        raw_scores = [
            formula(rows[i]) if mask_keep[i] else float("nan")
            for i in range(n)
        ]
        # Reuse compute's within-type percentile rank (NaN rows stay NaN/null).
        ranked = compute._percentile_within_type(pd.Series(raw_scores))
        opp[t] = [
            None if pd.isna(v) else round(float(v), 4)
            for v in ranked
        ]

    opp_cafe = opp["cafe"]
    opp_bakery = opp["bakery"]
    opp_confectionery = opp["confectionery"]

    # --- Assemble GeoJSON FeatureCollection -----------------------------------
    features = []
    for i in range(n):
        cx, cy = centers[i]
        props = {
            "unit_id": "sample-%04d" % (i + 1),
            "traffic": traffic[i],
            "transit": round(transit[i], 4),
            "offices": int(raw[i]["offices"]),
            "residential": round(residential[i], 1),
            "income": round(income[i], 1),
            "n_food": int(n_food[i]),
            "traffic_norm": round(traffic_norm[i], 4),
            "transit_norm": round(transit_norm[i], 4),
            "residential_norm": round(residential_norm[i], 4),
            "income_norm": round(income_norm[i], 4),
            "comp_cafe": int(comp_cafe[i]),
            "comp_bakery": int(comp_bakery[i]),
            "comp_confectionery": int(comp_confectionery[i]),
            "gap_cafe": gap_cafe[i],
            "gap_bakery": gap_bakery[i],
            "gap_confectionery": gap_confectionery[i],
            "opp_cafe": opp_cafe[i],
            "opp_bakery": opp_bakery[i],
            "opp_confectionery": opp_confectionery[i],
            "vegan_coverage": round(raw[i]["vegan"], 4),
            "vegetarian_coverage": round(raw[i]["vegetarian"], 4),
            "glutenfree_coverage": round(raw[i]["glutenfree"], 4),
            "halal_coverage": round(raw[i]["halal"], 4),
        }
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [hex_vertices(cx, cy, HEX_R)],
            },
            "properties": props,
        }
        features.append(feature)

    fc = {
        "type": "FeatureCollection",
        "features": features,
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fc, f, indent=2)

    # Brief console summary (this script is run manually, not imported).
    veg = [raw[i]["vegan"] for i in range(n)]
    n_scored = {t: sum(1 for v in opp[t] if v is not None) for t in config.TYPES}
    print("Wrote %d features to %s" % (len(features), out_path))
    print("vegan_coverage mean=%.4f  zeros=%d/%d"
          % (sum(veg) / len(veg), sum(1 for v in veg if v == 0.0), n))
    print("sectors with scores per type: %s" % n_scored)
    print("cells gated out (no score) = %d/%d"
          % (sum(1 for k in mask_keep if not k), n))


def _parse_args():
    p = argparse.ArgumentParser(description="Generate a SpotFinder sample GeoJSON.")
    p.add_argument(
        "--out", default=DEFAULT_OUT,
        help="output path (default: backend/data/sample.geojson; "
             "must not be a real city file)",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(out_path=args.out)
