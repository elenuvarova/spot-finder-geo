#!/usr/bin/env python3
"""Synthetic sample dataset generator for SpotFinder.

Produces backend/data/antwerpen.geojson: a WGS84 / EPSG:4326 FeatureCollection
of ~60 pointy-top hexagon cells tiling a bounding box around Antwerp.

This is SYNTHETIC data so the backend and frontend can be developed and tested
before the real pipeline runs. Every cell carries the full property schema the
real pipeline must agree on (see the GeoJSON CONTRACT in the project docs).

Honest framing reminder for downstream copy: traffic is a PROXY (signals, not
guarantees) and vegan_coverage reflects the diet:vegan tag, which undercounts
reality. The numbers here are plausible but invented.

Standard library only.
"""

import json
import math
import random

# --- Bounding box around Antwerp (EPSG:4326) ---------------------------------
LON_MIN, LON_MAX = 4.36, 4.47
LAT_MIN, LAT_MAX = 51.17, 51.25

# Hex geometry. Pointy-top hexagons with a circumradius of ~0.006 deg.
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
    hex and its ring of neighbors for the traffic proxy and competitor counts.
    """
    cx, cy = centers[idx]
    out = []
    for j, (ox, oy) in enumerate(centers):
        if (ox - cx) ** 2 + (oy - cy) ** 2 <= radius ** 2:
            out.append(j)
    return out


def minmax_norm(values):
    """Min-max normalize a list to 0..1. Constant lists map to 0.0."""
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span == 0:
        return [0.0 for _ in values]
    return [(v - lo) / span for v in values]


def percentile_ranks(pairs):
    """Percentile rank (0..1) of each raw score WITHIN a type.

    `pairs` is a list of (index, raw) for the cells that qualify (n_food >= 3).
    This MUST match pipeline/compute.py `_percentile_within_type` exactly so the
    synthetic sample and the real pipeline agree:
      * average-rank percentile (tied values share the average rank), giving a
        value in (0, 1] = rank / n;
      * then a min-max rescale so the minimum maps to 0 and the maximum to 1
        (an all-equal set rescales to all 0.0);
      * a single qualifying cell returns 1.0 (NOT 0.0).
    Returns {index: rank}.
    """
    n = len(pairs)
    ranks = {}
    if n == 0:
        return ranks
    if n == 1:
        ranks[pairs[0][0]] = 1.0
        return ranks

    # Average-rank percentile in (0, 1]: for each distinct value, the average of
    # the 1-based ordinal positions it occupies, divided by n (matches pandas
    # rank(method="average", pct=True)).
    raws = sorted(r for _, r in pairs)
    avg_rank = {}
    i = 0
    while i < n:
        j = i
        while j < n and raws[j] == raws[i]:
            j += 1
        # positions i+1 .. j (1-based) share this value; their average rank.
        mean_pos = (i + 1 + j) / 2.0
        avg_rank[raws[i]] = mean_pos
        i = j
    pct = {idx: avg_rank[raw] / n for idx, raw in pairs}

    # Min-max rescale so min -> 0 and max -> 1 (all-equal -> all 0.0).
    lo = min(pct.values())
    hi = max(pct.values())
    span = hi - lo
    for idx in pct:
        ranks[idx] = (pct[idx] - lo) / span if span > 0 else 0.0
    return ranks


def main():
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

        # Food establishments in the hex (small integers); some below the
        # noise threshold of 3 so their opportunity scores become null.
        n_food = random.choices(
            population=[0, 1, 2, 3, 4, 5, 6, 8, 11, 15],
            weights=[10, 12, 12, 11, 10, 9, 8, 7, 6, 5],
            k=1,
        )[0]
        n_food = int(round(n_food * (0.4 + 0.9 * centrality)))

        # Vegan coverage: skewed low, plenty of zeros (the tag undercounts).
        if random.random() < 0.35:
            vegan = 0.0
        else:
            # Beta-ish skew toward 0 via min of two uniforms.
            vegan = round(min(random.random(), random.random()) * 0.45, 4)

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

    # --- Normalized drivers (min-max across all hexes) ------------------------
    traffic_norm = minmax_norm(traffic)
    transit_norm = minmax_norm(transit)
    residential_norm = minmax_norm(residential)
    income_norm = minmax_norm(income)

    # gap_norm_<type>: bigger gap maps closer to 1.
    gap_norm_cafe = minmax_norm(gap_cafe)
    gap_norm_bakery = minmax_norm(gap_bakery)
    gap_norm_confectionery = minmax_norm(gap_confectionery)

    # --- Per-type raw opportunity formulas ------------------------------------
    # Each type uses DIFFERENT inputs; they are intentionally not collapsed.
    raw_cafe = []
    raw_bakery = []
    raw_conf = []
    for i in range(n):
        # cafe: destination, daytime traffic.
        rc = ((traffic_norm[i] + 0.5 * transit_norm[i]) * income_norm[i]
              / (1 + comp_cafe[i]))
        # bakery: convenience; traffic/offices intentionally NOT used.
        rb = (residential_norm[i] * gap_norm_bakery[i]
              * (0.5 + 0.5 * income_norm[i]) / (1 + comp_bakery[i]))
        # confectionery: discretionary, light destination.
        rf = (income_norm[i] * (0.6 * traffic_norm[i] + 0.4 * residential_norm[i])
              / (1 + comp_confectionery[i]))
        raw_cafe.append(rc)
        raw_bakery.append(rb)
        raw_conf.append(rf)

    # --- Percentile rank WITHIN type, only for n_food >= 3 (else null) --------
    def opp_for(raw_scores):
        pairs = [(i, raw_scores[i]) for i in range(n) if n_food[i] >= 3]
        ranks = percentile_ranks(pairs)
        out = []
        for i in range(n):
            if n_food[i] < 3:
                out.append(None)
            else:
                out.append(round(ranks[i], 4))
        return out

    opp_cafe = opp_for(raw_cafe)
    opp_bakery = opp_for(raw_bakery)
    opp_confectionery = opp_for(raw_conf)

    # --- Assemble GeoJSON FeatureCollection -----------------------------------
    features = []
    for i in range(n):
        cx, cy = centers[i]
        props = {
            "h3": "sample-%04d" % (i + 1),
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

    import os
    out_dir = os.path.join("backend", "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "antwerpen.geojson")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fc, f, indent=2)

    # Brief console summary (this script is run manually, not imported).
    veg = [raw[i]["vegan"] for i in range(n)]
    print("Wrote %d features to %s" % (len(features), out_path))
    print("vegan_coverage mean=%.4f  zeros=%d/%d"
          % (sum(veg) / len(veg), sum(1 for v in veg if v == 0.0), n))
    print("cells with n_food<3 (opp_* null)=%d/%d"
          % (sum(1 for x in n_food if x < 3), n))


if __name__ == "__main__":
    main()
