"""Stage 3: clean and normalize the raw OSM points.

Responsibilities:
  * Classify each raw OSM point into a SpotFinder type (cafe / bakery /
    confectionery) and/or an attractor role (gastro / retail / transit /
    offices). A single point can be an attractor without being a scored type.
    The "confectionery" type MERGES shop=pastry + shop=confectionery into one
    (Phase 0); it is a thin sample (33) flagged LOW-CONFIDENCE in config.
  * Filter Belgian "cafe-bars" out of amenity=cafe (drop bar=yes,
    alcohol-ish cuisine, real_ale, microbrewery/brewery). Explicit alcohol tags
    catch only ~2/281 cafes, so the cafe count is an UPPER BOUND (see config).
  * Derive the vegan flag from the documented diet:vegan tag only
    (diet:vegan in {yes, only}); cuisine=vegan is deliberately NOT used.
  * Emit a single cleaned point layer with stable, typed columns.

Run:  python pipeline/clean.py
Input:  pipeline/data/osm_points_raw.geojson
Output: pipeline/data/osm_points_clean.geojson
"""

import json
import os

import config


def _matches(tags, taglist):
    """True if tags contain ANY (key, value) pair in taglist ('*' = any value)."""
    for key, value in taglist:
        if key in tags:
            if value == "*" or tags[key] == value:
                return True
    return False


def _split_multi(value):
    """OSM multi-values are ';'-separated (e.g. cuisine=coffee_shop;beer)."""
    if not value:
        return set()
    return {part.strip().lower() for part in str(value).split(";") if part.strip()}


def _is_belgian_cafe_bar(tags):
    """True if an amenity=cafe is really a drinking cafe-bar we should drop.

    Drops the cafe if ANY of:
      * bar=yes
      * cuisine contains an alcohol-ish value (beer/pub/bar/wine/brewery)
      * real_ale present (yes/only/sometimes)
      * microbrewery / brewery present
    """
    for key, drop_values in config.CAFE_BAR_DROP.items():
        if key in tags and str(tags[key]).strip().lower() in drop_values:
            return True
    cuisines = _split_multi(tags.get("cuisine"))
    if cuisines & config.CAFE_BAR_ALCOHOL_CUISINES:
        return True
    return False


def _classify_type(tags):
    """Return the scored SpotFinder type for these tags, or None.

    A point is classified into at most one scored type. Cafes that are really
    Belgian cafe-bars are dropped (return None even though amenity=cafe matched).
    """
    for type_name, taglist in config.OSM_TYPE_TAGS.items():
        if _matches(tags, taglist):
            if type_name == "cafe" and _is_belgian_cafe_bar(tags):
                return None  # dropped: it's a drinking bar, not a coffee cafe
            return type_name
    return None


def _classify_attractor_roles(tags):
    """Return the set of attractor roles a point fills (may be empty)."""
    roles = set()
    for role, taglist in config.ATTRACTOR_TAGS.items():
        if _matches(tags, taglist):
            roles.add(role)
    return roles


def _vegan_flag(tags):
    """Derive vegan flag from diet:vegan in {yes, only}; cuisine=vegan NOT used."""
    val = tags.get(config.VEGAN_DIET_TAG)
    if val is None:
        return False
    return str(val).strip().lower() in config.VEGAN_POSITIVE_VALUES


def clean():
    """Read the raw OSM layer, classify/filter, and write the clean layer."""
    with open(config.OSM_POINTS_PATH, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    features_out = []
    dropped_cafe_bars = 0
    counts = {"cafe": 0, "bakery": 0, "confectionery": 0,
              "gastro": 0, "retail": 0, "transit": 0, "offices": 0}
    vegan_count = 0

    # Deduplicate: a real place can appear as both a node and an enclosing way.
    # Keyed on (rounded lon/lat, primary classification) so we don't double-count.
    seen_keys = set()

    for feat in raw.get("features", []):
        tags = feat.get("properties", {}) or {}
        lon, lat = feat["geometry"]["coordinates"]

        spot_type = _classify_type(tags)
        roles = _classify_attractor_roles(tags)

        # Track cafe-bars we dropped (matched amenity=cafe but filtered out).
        if spot_type is None and _matches(tags, config.OSM_TYPE_TAGS["cafe"]) \
                and _is_belgian_cafe_bar(tags):
            dropped_cafe_bars += 1

        # Skip points that are neither a scored type nor any attractor.
        if spot_type is None and not roles:
            continue

        is_food = spot_type is not None  # all three scored types are "food"
        vegan = _vegan_flag(tags) if is_food else False

        # Deduplicate on coarse location + role signature.
        key = (round(lon, 6), round(lat, 6), spot_type, tuple(sorted(roles)))
        if key in seen_keys:
            continue
        seen_keys.add(key)

        if spot_type:
            counts[spot_type] += 1
        for r in roles:
            counts[r] += 1
        if vegan:
            vegan_count += 1

        props = {
            "osm_type": tags.get("osm_type"),
            "osm_id": tags.get("osm_id"),
            "spot_type": spot_type,                 # cafe/bakery/confectionery or None
            "is_food": bool(is_food),
            "is_gastro": "gastro" in roles,
            "is_retail": "retail" in roles,
            "is_transit": "transit" in roles,
            "is_office": "offices" in roles,
            "vegan": bool(vegan),
            "name": tags.get("name"),
        }
        features_out.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })

    os.makedirs(config.DATA_DIR, exist_ok=True)
    fc = {"type": "FeatureCollection", "features": features_out}
    with open(config.CLEAN_POINTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(fc, fh, ensure_ascii=False)

    # Cafe count is an UPPER BOUND: explicit alcohol tags catch only ~2/281
    # Belgian cafe-bars, so this filter is a floor, not a fix (Phase 0).
    print(f"[clean] dropped Belgian cafe-bars from amenity=cafe: {dropped_cafe_bars} "
          f"(explicit tags under-detect; cafe count is an UPPER BOUND)")
    print(f"[clean] classified counts: {counts}")
    if config.TYPE_LOW_CONFIDENCE.get("confectionery"):
        print(f"[clean] NOTE: 'confectionery' (pastry+confectionery merged) is a "
              f"thin sample -> LOW-CONFIDENCE; got {counts['confectionery']}")
    print(f"[clean] documented diet:vegan establishments: {vegan_count}")
    print(f"[clean] wrote {len(features_out)} clean points -> {config.CLEAN_POINTS_PATH}")
    return config.CLEAN_POINTS_PATH


if __name__ == "__main__":
    clean()
