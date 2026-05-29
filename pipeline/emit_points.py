"""Stage 6: emit the per-POINT layer the backend serves at /api/points.

Each cleaned OSM point (an eatery, a transit stop, an office, a retail
storefront, ...) becomes ONE GeoJSON feature, tagged with the Statbel
statistical sector that CONTAINS it (unit_id = str(CD_SECTOR)). Points that
fall outside every sector get unit_id=None. Diet flags (vegan / vegetarian /
gluten-free / halal) ride along from clean.py and each UNDERCOUNTS reality.

Run:  python pipeline/emit_points.py
Inputs:  pipeline/data/<city>_osm_points_clean.geojson,
         pipeline/data/<city>_statbel_sectors.geojson
Output:  backend/data/<city>_points.geojson  (one feature per cleaned point)
"""

import json
import os

import geopandas as gpd
from shapely.geometry import Point

import config


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
            "name": p.get("name"),
            "spot_type": p.get("spot_type"),
            "is_food": bool(p.get("is_food")),
            "is_gastro": bool(p.get("is_gastro")),
            "is_retail": bool(p.get("is_retail")),
            "is_transit": bool(p.get("is_transit")),
            "is_office": bool(p.get("is_office")),
            "diet_vegan": bool(p.get("diet_vegan")),
            "diet_vegetarian": bool(p.get("diet_vegetarian")),
            "diet_glutenfree": bool(p.get("diet_glutenfree")),
            "diet_halal": bool(p.get("diet_halal")),
            "geometry": Point(lon, lat),
        })
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=config.OUTPUT_CRS)


def _load_sectors():
    """Load Statbel sectors (polygons) in WGS84."""
    sectors = gpd.read_file(config.STATBEL_SECTORS_PATH)
    if sectors.crs is None:
        sectors = sectors.set_crs(config.OUTPUT_CRS)
    elif str(sectors.crs).upper() != "EPSG:4326":
        sectors = sectors.to_crs(config.OUTPUT_CRS)
    return sectors.reset_index(drop=True)


def emit_points():
    """Assign each point its containing sector and write the point GeoJSON."""
    points = _load_points()
    sectors = _load_sectors()
    print(f"[emit_points] {len(points)} points, {len(sectors)} Statbel sectors")

    code_f = config.STATBEL_SECTOR_CODE_FIELD

    # Assign each point the sector that CONTAINS it (within). Points outside
    # every sector keep unit_id=None. how="left" preserves all points.
    joined = gpd.sjoin(
        points, sectors[[code_f, "geometry"]], how="left", predicate="within"
    )
    # A point on a shared boundary could match >1 sector; keep the first.
    joined = joined[~joined.index.duplicated(keep="first")]

    features = []
    for _, r in joined.iterrows():
        code = r.get(code_f)
        unit_id = None if (code is None or (isinstance(code, float) and code != code)) \
            else str(code)
        is_eatery = bool(r["is_food"]) or bool(r["is_gastro"])
        props = {
            "name": r["name"] if r["name"] else None,
            "spot_type": r["spot_type"] if r["spot_type"] else None,
            "is_eatery": is_eatery,
            "is_gastro": bool(r["is_gastro"]),
            "is_retail": bool(r["is_retail"]),
            "is_transit": bool(r["is_transit"]),
            "is_office": bool(r["is_office"]),
            "diet_vegan": bool(r["diet_vegan"]),
            "diet_vegetarian": bool(r["diet_vegetarian"]),
            "diet_glutenfree": bool(r["diet_glutenfree"]),
            "diet_halal": bool(r["diet_halal"]),
            "unit_id": unit_id,
        }
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": props,
        })

    fc = {"type": "FeatureCollection", "features": features}
    os.makedirs(os.path.dirname(config.POINTS_OUTPUT_PATH), exist_ok=True)
    with open(config.POINTS_OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(fc, fh, ensure_ascii=False)

    n_assigned = sum(1 for f in features if f["properties"]["unit_id"] is not None)
    print(f"[emit_points] wrote {len(features)} points -> {config.POINTS_OUTPUT_PATH} "
          f"({n_assigned} inside a sector, {len(features) - n_assigned} outside)")
    return config.POINTS_OUTPUT_PATH


if __name__ == "__main__":
    emit_points()
