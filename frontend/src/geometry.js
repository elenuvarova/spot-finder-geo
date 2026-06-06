// Geometry helpers for GeoJSON Polygon / MultiPolygon features.
//
// These are deliberately simple coordinate averages / extents — good enough for
// placing markers and fitting the map to a set of sectors, with no projection
// or area weighting.

/**
 * Compute a rough centroid (mean of vertices) for a GeoJSON geometry.
 *
 * For a Polygon the outer ring is used. For a MultiPolygon the outer rings of
 * every part are averaged together (each vertex weighted equally).
 *
 * @param {object} geometry - a GeoJSON geometry (Polygon or MultiPolygon).
 * @returns {number[]|null} [lon, lat], or null when there are no coordinates
 *   (so callers don't fly to [0, 0] in the ocean off West Africa).
 */
export function centroid(geometry) {
  let sumLon = 0;
  let sumLat = 0;
  let count = 0;

  const addRing = (ring) => {
    if (!Array.isArray(ring)) return;
    for (const coord of ring) {
      if (!Array.isArray(coord)) continue;
      sumLon += Number(coord[0]);
      sumLat += Number(coord[1]);
      count += 1;
    }
  };

  if (geometry && geometry.type === 'Polygon') {
    addRing(geometry.coordinates && geometry.coordinates[0]);
  } else if (geometry && geometry.type === 'MultiPolygon') {
    const polys = geometry.coordinates || [];
    for (const poly of polys) {
      addRing(poly && poly[0]);
    }
  }

  if (count === 0) return null;
  return [sumLon / count, sumLat / count];
}

/**
 * Compute the bounding box of an array of GeoJSON features.
 *
 * Iterates every vertex of each feature's Polygon / MultiPolygon geometry
 * (all rings, not just the outer ones).
 *
 * @param {Array<object>} features - GeoJSON features.
 * @returns {Array<number[]>|null} [[minLon,minLat],[maxLon,maxLat]], or null if empty.
 */
export function bounds(features) {
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;
  let seen = false;

  const addCoord = (coord) => {
    if (!Array.isArray(coord)) return;
    const lon = Number(coord[0]);
    const lat = Number(coord[1]);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
    if (lon < minLon) minLon = lon;
    if (lat < minLat) minLat = lat;
    if (lon > maxLon) maxLon = lon;
    if (lat > maxLat) maxLat = lat;
    seen = true;
  };

  const addRing = (ring) => {
    if (!Array.isArray(ring)) return;
    for (const coord of ring) addCoord(coord);
  };

  for (const feature of features || []) {
    const geometry = feature && feature.geometry;
    if (!geometry) continue;
    if (geometry.type === 'Polygon') {
      for (const ring of geometry.coordinates || []) addRing(ring);
    } else if (geometry.type === 'MultiPolygon') {
      for (const poly of geometry.coordinates || []) {
        for (const ring of poly || []) addRing(ring);
      }
    }
  }

  if (!seen) return null;
  return [
    [minLon, minLat],
    [maxLon, maxLat],
  ];
}
