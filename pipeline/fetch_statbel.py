"""Stage 2: fetch Belgian Statbel statistical-sector data for Antwerp.

Downloads three Statbel open datasets keyed by statistical-sector code:
  1. sector GEOMETRY  (EPSG:31370 Belgian Lambert 72)
  2. fiscal INCOME    (avg net taxable income per sector, EUR)
  3. POPULATION       (population per sector)

It joins INCOME and POPULATION onto the geometry by sector code, REPROJECTS
the geometry to WGS84 (EPSG:4326) with gdf.to_crs(4326), logs the share of
sectors that fail to merge, clips to the Antwerp bbox, and writes a sector
GeoJSON for build_grid.py.

Run:  python pipeline/fetch_statbel.py
Output: pipeline/data/statbel_sectors.geojson
"""

import io
import os
import time
import zipfile

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import box

import config


def _download(url):
    """Download a URL to bytes, caching the national Statbel files on disk.

    The Statbel datasets are national (identical for every city), so each
    download is cached under pipeline/data/statbel_cache/ and reused across
    cities — a second city (e.g. Leuven) needs no Statbel re-download.
    """
    cache_dir = os.path.join(config.DATA_DIR, "statbel_cache")
    os.makedirs(cache_dir, exist_ok=True)
    name = url.rstrip("/").split("/")[-1].split("?")[0] or "download.bin"
    cache_path = os.path.join(cache_dir, name)
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        print(f"[fetch_statbel] using cached {name}")
        with open(cache_path, "rb") as fh:
            return fh.read()

    headers = {"User-Agent": config.USER_AGENT}
    last_exc = None
    for attempt in range(config.HTTP_MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=config.HTTP_TIMEOUT_S)
        except requests.RequestException as exc:
            last_exc = exc
            wait = config.HTTP_BACKOFF_BASE_S * (2 ** attempt)
            print(f"[fetch_statbel] request error ({exc}); retry in {wait:.0f}s")
            time.sleep(wait)
            continue
        if resp.status_code in (429, 502, 503, 504):
            retry_after = resp.headers.get("Retry-After")
            wait = (float(retry_after) if retry_after and retry_after.isdigit()
                    else config.HTTP_BACKOFF_BASE_S * (2 ** attempt))
            print(f"[fetch_statbel] HTTP {resp.status_code}; backing off {wait:.0f}s")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        with open(cache_path, "wb") as fh:
            fh.write(resp.content)
        return resp.content
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"download failed after retries: {url}")


def _read_geometry(content, url):
    """Read the sector geometry from bytes.

    Statbel ships geometry either as a zipped GeoJSON/Shapefile or as a plain
    GeoJSON. We handle both: if it is a zip we hand the in-memory bytes to
    GeoPandas via a /vsizip/ virtual path so we never have to extract to disk.
    """
    if zipfile.is_zipfile(io.BytesIO(content)):
        # Persist the zip so GDAL's /vsizip/ can open the contained layer.
        os.makedirs(config.DATA_DIR, exist_ok=True)
        zip_path = os.path.join(config.DATA_DIR, "statbel_sectors_src.zip")
        with open(zip_path, "wb") as fh:
            fh.write(content)
        zf = zipfile.ZipFile(zip_path)
        # Prefer a contained .geojson, else fall back to a .shp.
        names = zf.namelist()
        inner = next((n for n in names if n.lower().endswith(".geojson")), None)
        if inner is None:
            inner = next((n for n in names if n.lower().endswith(".shp")), None)
        if inner is None:
            raise RuntimeError(f"no .geojson/.shp inside Statbel zip: {names}")
        return gpd.read_file(f"/vsizip/{zip_path}/{inner}")
    # Plain (geo)json bytes.
    return gpd.read_file(io.BytesIO(content))


def _read_table(content):
    """Read a Statbel statistics table from bytes (xlsx, csv, or txt)."""
    bio = io.BytesIO(content)
    # Try Excel first (the .xlsx open-data files), then delimited text.
    try:
        return pd.read_excel(bio, engine="openpyxl")
    except Exception:
        bio.seek(0)
        # Statbel CSV/TXT exports are typically '|' or ';' delimited.
        for sep in ("|", ";", ","):
            bio.seek(0)
            try:
                df = pd.read_csv(bio, sep=sep)
                if df.shape[1] > 1:
                    return df
            except Exception:
                continue
        raise RuntimeError("could not parse Statbel statistics table")


def _find_col(df, candidates):
    """Return the first column in df whose name matches any candidate.

    Statbel column headers vary by year/language (CD_SECTOR / cd_sector /
    'Code sector'). We match case-insensitively on a list of candidates.
    """
    lower_map = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    # Substring fallback.
    for cand in candidates:
        for col in df.columns:
            if cand.lower() in col.lower():
                return col
    return None


def fetch_statbel():
    """Download, join, reproject, clip and write the sector layer."""
    os.makedirs(config.DATA_DIR, exist_ok=True)

    # --- 1. geometry -------------------------------------------------------
    print("[fetch_statbel] downloading sector geometry ...")
    geom_bytes = _download(config.STATBEL_SECTOR_GEOMETRY_URL)
    sectors = _read_geometry(geom_bytes, config.STATBEL_SECTOR_GEOMETRY_URL)
    print(f"[fetch_statbel] geometry: {len(sectors)} sectors")

    # Ensure the geometry has a CRS, then REPROJECT to WGS84. The source is
    # EPSG:31370 (Belgian Lambert 72); if the file lacks CRS metadata we set it.
    if sectors.crs is None:
        sectors = sectors.set_crs(config.STATBEL_SOURCE_CRS)
    sectors = sectors.to_crs(config.OUTPUT_CRS)

    # Reconcile the sector-code column to the canonical name.
    # The Statbel sector SHAPEFILE names its sector-code column after the
    # geometry vintage date, e.g. the 2022 file uses "CS01012022" (and older
    # vintages "CS01012020", "CS01012018", ...). The statistics tables instead
    # use "CD_SECTOR". The codes themselves are identical strings ('11002A00-'),
    # so we list the dated CS0101<year> variants here and rename to CD_SECTOR.
    geom_code = _find_col(sectors, [config.STATBEL_SECTOR_CODE_FIELD,
                                    "CD_SECTOR",
                                    "CS01012022", "CS01012021", "CS01012020",
                                    "CS01012019", "CS01012018",
                                    "SECTOR_CD", "Code sector", "sectorcode"])
    if geom_code is None:
        raise RuntimeError(
            f"geometry has no recognisable sector-code column; got {list(sectors.columns)}")
    sectors = sectors.rename(columns={geom_code: config.STATBEL_SECTOR_CODE_FIELD})
    sectors[config.STATBEL_SECTOR_CODE_FIELD] = (
        sectors[config.STATBEL_SECTOR_CODE_FIELD].astype(str).str.strip())

    total_sectors = len(sectors)

    # --- 2. income ---------------------------------------------------------
    print("[fetch_statbel] downloading fiscal income ...")
    income_df = _read_table(_download(config.STATBEL_INCOME_URL))
    inc_code = _find_col(income_df, [config.STATBEL_SECTOR_CODE_FIELD,
                                     "CD_SECTOR", "SECTOR_CD", "sectorcode"])
    inc_val = _find_col(income_df, ["MEAN_INCOME", "MS_AVG_TOT_NET_TAXABLE_INC",
                                    "avg_income", "mean_income",
                                    "Gemiddeld inkomen", "Revenu moyen"])
    if inc_code is None or inc_val is None:
        raise RuntimeError(
            f"income table missing code/value columns; got {list(income_df.columns)}")
    # The fiscal-income xlsx is a TIME SERIES: one row per (sector, income year)
    # for every year 2005..2023 (~378k rows, ~19 rows per sector). We want the
    # MOST RECENT income year only -- averaging across two decades would badly
    # understate today's income and conflate a long upward trend into one value.
    # If a year column is present, keep only its maximum (latest) year first.
    inc_year = _find_col(income_df, ["CD_YEAR", "year", "annee", "jaar"])
    if inc_year is not None:
        years = pd.to_numeric(income_df[inc_year], errors="coerce")
        latest = years.max()
        income_df = income_df[years == latest].copy()
        print(f"[fetch_statbel] income: keeping latest year {int(latest)} "
              f"({len(income_df)} sector rows)")
    income_df = income_df[[inc_code, inc_val]].rename(columns={
        inc_code: config.STATBEL_SECTOR_CODE_FIELD,
        inc_val: config.STATBEL_INCOME_FIELD,
    })
    income_df[config.STATBEL_SECTOR_CODE_FIELD] = (
        income_df[config.STATBEL_SECTOR_CODE_FIELD].astype(str).str.strip())
    income_df[config.STATBEL_INCOME_FIELD] = pd.to_numeric(
        income_df[config.STATBEL_INCOME_FIELD], errors="coerce")
    # Collapse to one row per sector (defensive against any residual dupes).
    income_df = income_df.groupby(config.STATBEL_SECTOR_CODE_FIELD, as_index=False).mean()

    # --- 3. population -----------------------------------------------------
    print("[fetch_statbel] downloading population ...")
    pop_df = _read_table(_download(config.STATBEL_POPULATION_URL))
    pop_code = _find_col(pop_df, [config.STATBEL_SECTOR_CODE_FIELD,
                                  "CD_SECTOR", "SECTOR_CD", "sectorcode"])
    pop_val = _find_col(pop_df, ["POPULATION", "TOTAL", "MS_POPULATION",
                                 "Aantal", "Population", "Bevolking"])
    if pop_code is None or pop_val is None:
        raise RuntimeError(
            f"population table missing code/value columns; got {list(pop_df.columns)}")
    pop_df = pop_df[[pop_code, pop_val]].rename(columns={
        pop_code: config.STATBEL_SECTOR_CODE_FIELD,
        pop_val: config.STATBEL_POPULATION_FIELD,
    })
    pop_df[config.STATBEL_SECTOR_CODE_FIELD] = (
        pop_df[config.STATBEL_SECTOR_CODE_FIELD].astype(str).str.strip())
    pop_df[config.STATBEL_POPULATION_FIELD] = pd.to_numeric(
        pop_df[config.STATBEL_POPULATION_FIELD], errors="coerce")
    pop_df = pop_df.groupby(config.STATBEL_SECTOR_CODE_FIELD, as_index=False).sum()

    # --- 4. join by sector code -------------------------------------------
    merged = sectors.merge(income_df, on=config.STATBEL_SECTOR_CODE_FIELD, how="left")
    merged = merged.merge(pop_df, on=config.STATBEL_SECTOR_CODE_FIELD, how="left")

    # Log the share of sectors that failed to pick up each statistic.
    n_no_income = int(merged[config.STATBEL_INCOME_FIELD].isna().sum())
    n_no_pop = int(merged[config.STATBEL_POPULATION_FIELD].isna().sum())
    print(f"[fetch_statbel] sectors failing income merge: "
          f"{n_no_income}/{total_sectors} ({100.0 * n_no_income / total_sectors:.1f}%)")
    print(f"[fetch_statbel] sectors failing population merge: "
          f"{n_no_pop}/{total_sectors} ({100.0 * n_no_pop / total_sectors:.1f}%)")

    # --- 5. clip to the active city's bbox --------------------------------
    s, w, n, e = config.BBOX
    bbox_geom = box(w, s, e, n)  # shapely box takes (minx, miny, maxx, maxy)
    before = len(merged)
    merged = merged[merged.intersects(bbox_geom)].copy()
    print(f"[fetch_statbel] clipped sectors to {config.CITY_NAME} bbox: "
          f"{len(merged)}/{before} retained")

    # Keep only the columns the rest of the pipeline needs.
    keep = [config.STATBEL_SECTOR_CODE_FIELD, config.STATBEL_INCOME_FIELD,
            config.STATBEL_POPULATION_FIELD, "geometry"]
    merged = merged[[c for c in keep if c in merged.columns]]

    merged.to_file(config.STATBEL_SECTORS_PATH, driver="GeoJSON")
    print(f"[fetch_statbel] wrote {len(merged)} sectors -> {config.STATBEL_SECTORS_PATH}")
    return config.STATBEL_SECTORS_PATH


if __name__ == "__main__":
    fetch_statbel()
