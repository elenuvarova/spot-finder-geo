// Thin API client for the SpotFinder backend.
//
// The base URL comes from Vite's env (VITE_API_URL); it defaults to the local
// FastAPI server. NO API KEY is ever read or sent from the frontend — the
// backend holds any keys and proxies the AI calls.

const BASE_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '');

/**
 * Fetch the full Antwerp FeatureCollection.
 *
 * The backend may be a cold-starting free dyno, so callers should show a
 * patient loading state. We use a long timeout to tolerate the ~30-50s wake-up.
 *
 * @returns {Promise<object>} a GeoJSON FeatureCollection.
 */
export async function getSpots() {
  const controller = new AbortController();
  // Generous timeout to survive a cold start.
  const timeout = setTimeout(() => controller.abort(), 90000);

  try {
    const res = await fetch(`${BASE_URL}/api/spots`, {
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
 * Ask the backend for an explanation of a hex.
 *
 * The backend NEVER returns a 5xx for this endpoint: on any AI failure it falls
 * back to the template and returns { explanation, source: "template" }. We still
 * guard against transport errors so callers can keep the local template text.
 *
 * @param {object} payload - { type, vegan, props }.
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
