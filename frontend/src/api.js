// Thin API client for the SpotFinder backend.
//
// The base URL comes from Vite's env (VITE_API_URL). It DEFAULTS to '' (empty),
// i.e. a relative same-origin base, so the production build talks to /api/* on
// whatever host serves it — used by the single-service Render deploy where
// FastAPI serves both the API and this built frontend. For local two-process
// dev (Vite on :5173, backend on another port) set VITE_API_URL in a .env.local
// (e.g. http://localhost:8001). NO API KEY is ever read or sent from the
// frontend — the backend holds any keys and proxies the AI calls.

const BASE_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/+$/, '');

/**
 * Fetch the full Antwerp FeatureCollection.
 *
 * The backend may be a cold-starting free dyno, so callers should show a
 * patient loading state. We use a long timeout to tolerate the ~30-50s wake-up.
 *
 * @returns {Promise<object>} a GeoJSON FeatureCollection.
 */
export async function getSpots(city) {
  const controller = new AbortController();
  // Generous timeout to survive a cold start.
  const timeout = setTimeout(() => controller.abort(), 90000);
  const qs = city ? `?city=${encodeURIComponent(city)}` : '';

  try {
    const res = await fetch(`${BASE_URL}/api/spots${qs}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });

    if (!res.ok) {
      throw new Error(`Failed to load spots (HTTP ${res.status})`);
    }

    const data = await res.json();

    if (!data || data.type !== 'FeatureCollection' || !Array.isArray(data.features)) {
      throw new Error('Unexpected response shape from /api/spots');
    }

    return data;
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error('The backend took too long to respond (it may be waking up). Please retry.');
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * Fetch the points FeatureCollection for a city (establishments, transit, etc).
 *
 * This is a NEW, optional dataset: the backend returns 503 when a city's points
 * file is missing. Callers should treat ANY failure here as "no points" and keep
 * the map working — so this throws on any non-OK response and the caller decides
 * to swallow it (App sets points=null).
 *
 * @returns {Promise<object>} a GeoJSON FeatureCollection of Point features.
 */
export async function getPoints(city) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 90000);
  const qs = city ? `?city=${encodeURIComponent(city)}` : '';

  try {
    const res = await fetch(`${BASE_URL}/api/points${qs}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });

    if (!res.ok) {
      throw new Error(`Failed to load points (HTTP ${res.status})`);
    }

    const data = await res.json();

    if (!data || data.type !== 'FeatureCollection' || !Array.isArray(data.features)) {
      throw new Error('Unexpected response shape from /api/points');
    }

    return data;
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error('The backend took too long to respond (it may be waking up). Please retry.');
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * List the cities the backend can serve, with each city's map view.
 *
 * @returns {Promise<{cities: Array<{slug:string,name:string,center:number[],zoom:number}>, default: string}>}
 */
export async function getCities() {
  const res = await fetch(`${BASE_URL}/api/cities`, {
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) throw new Error(`Failed to load cities (HTTP ${res.status})`);
  return res.json();
}

/**
 * Ask the backend for an explanation of a hex.
 *
 * The backend NEVER returns a 5xx for this endpoint: on any AI failure it falls
 * back to the template and returns { explanation, source: "template" }. We still
 * guard against transport errors so callers can keep the local template text.
 *
 * @param {object} payload - { type, lens, props } (lens is a slug or null).
 * @returns {Promise<{explanation: string, source: 'ai'|'template'}>}
 */
export async function explain(payload) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);

  try {
    const res = await fetch(`${BASE_URL}/api/explain`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    if (!res.ok) {
      throw new Error(`Explain request failed (HTTP ${res.status})`);
    }

    const data = await res.json();
    if (!data || typeof data.explanation !== 'string') {
      throw new Error('Unexpected response shape from /api/explain');
    }
    return data;
  } finally {
    clearTimeout(timeout);
  }
}
