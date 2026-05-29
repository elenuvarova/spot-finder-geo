"""Stage 1: fetch OpenStreetMap data from Overpass for Antwerp.

Queries Overpass for the three scored business types, the attractor sets
(gastro, retail, transit, offices), and the documented diet:vegan tag, all
within the Antwerp bounding box. Emits a cleaned-but-not-yet-filtered point
layer (one record per OSM element) as GeoJSON for the next stage.

Run:  python pipeline/fetch_osm.py
Output: pipeline/data/osm_points_raw.geojson
"""

import json
import os
import time

import requests

import config


def _build_query():
    """Build a single Overpass QL query covering everything we need.

    We request nodes, ways and relations for each tag group and use `out center`
    so ways/relations collapse to a representative lon/lat. One combined query
    is far kinder to the shared Overpass service than many small ones.
    """
    bbox = config.overpass_bbox_str()

    # Collect every (key, value) selector we care about, de-duplicated.
    selectors = []

    def add(key, value):
        if value == "*":
            selectors.append(f'["{key}"]')
        else:
            selectors.append(f'["{key}"="{value}"]')

    # Scored types.
    for tags in config.OSM_TYPE_TAGS.values():
        for k, v in tags:
            add(k, v)
    # Attractors (gastro / retail / transit / offices).
    for tags in config.ATTRACTOR_TAGS.values():
        for k, v in tags:
            add(k, v)

    # De-duplicate while preserving order.
    seen = set()
    unique_selectors = []
    for sel in selectors:
        if sel not in seen:
            seen.add(sel)
            unique_selectors.append(sel)

    # Build statement lines for nodes/ways/relations for each selector.
    stmts = []
    for sel in unique_selectors:
        stmts.append(f"  node{sel}({bbox});")
        stmts.append(f"  way{sel}({bbox});")
        stmts.append(f"  relation{sel}({bbox});")

    body = "\n".join(stmts)
    query = (
        f"[out:json][timeout:{config.OVERPASS_TIMEOUT_S}];\n"
        f"(\n{body}\n);\n"
        f"out center tags;\n"
    )
    return query


def _post_with_retry(query):
    """POST the Overpass query with polite exponential backoff on 429/5xx."""
    headers = {"User-Agent": config.USER_AGENT}
    last_exc = None
    for attempt in range(config.HTTP_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                config.OVERPASS_URL,
                data={"data": query},
                headers=headers,
                timeout=config.HTTP_TIMEOUT_S,
            )
        except requests.RequestException as exc:
            last_exc = exc
            wait = config.HTTP_BACKOFF_BASE_S * (2 ** attempt)
            print(f"[fetch_osm] request error ({exc}); retry in {wait:.0f}s "
                  f"(attempt {attempt + 1}/{config.HTTP_MAX_RETRIES})")
            time.sleep(wait)
            continue

        # 429 (Too Many Requests) and 504 (gateway timeout) are the common
        # Overpass throttling responses; back off and retry.
        if resp.status_code in (429, 502, 503, 504):
            # Respect Retry-After if present, else exponential backoff.
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                wait = float(retry_after)
            else:
                wait = config.HTTP_BACKOFF_BASE_S * (2 ** attempt)
            print(f"[fetch_osm] HTTP {resp.status_code}; backing off {wait:.0f}s "
                  f"(attempt {attempt + 1}/{config.HTTP_MAX_RETRIES})")
            time.sleep(wait)
            continue

        resp.raise_for_status()
        return resp.json()

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Overpass query failed after retries (persistent throttling).")


def _element_lonlat(el):
    """Return (lon, lat) for a node, or the `center` for a way/relation."""
    if el["type"] == "node":
        return el.get("lon"), el.get("lat")
    center = el.get("center")
    if center:
        return center.get("lon"), center.get("lat")
    return None, None


def fetch_osm():
    """Query Overpass and write the raw point layer as GeoJSON."""
    os.makedirs(config.DATA_DIR, exist_ok=True)

    query = _build_query()
    print(f"[fetch_osm] querying Overpass for {config.CITY_NAME} ...")
    data = _post_with_retry(query)

    elements = data.get("elements", [])
    print(f"[fetch_osm] received {len(elements)} raw OSM elements")

    features = []
    skipped_no_geom = 0
    for el in elements:
        lon, lat = _element_lonlat(el)
        if lon is None or lat is None:
            skipped_no_geom += 1
            continue
        tags = el.get("tags", {}) or {}
        # Carry the OSM id/type so downstream stages can deduplicate if a single
        # real-world place is mapped as both a node and an enclosing way.
        props = {
            "osm_type": el["type"],
            "osm_id": el["id"],
        }
        # Flatten tags as plain properties (clean.py reads these directly).
        props.update(tags)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })

    if skipped_no_geom:
        print(f"[fetch_osm] skipped {skipped_no_geom} elements without geometry")

    fc = {"type": "FeatureCollection", "features": features}
    with open(config.OSM_POINTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(fc, fh, ensure_ascii=False)

    print(f"[fetch_osm] wrote {len(features)} points -> {config.OSM_POINTS_PATH}")
    return config.OSM_POINTS_PATH


if __name__ == "__main__":
    fetch_osm()
