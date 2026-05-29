// Blend — the single source of truth for how a sector's score is computed.
//
// A "blend" decides what the score means:
//   { mode: 'default' }                          -> the precomputed opp_<type> value
//   { mode: 'custom', weights: {...} }           -> a custom weighted mix of drivers
//
// scoreFeature() is the canonical JS scorer; buildScoreExpression() returns a
// MapLibre GL expression that yields the SAME number for paint, minus the
// null-grey case (the Map handles non-scorable sectors separately).

import { getLens } from './lenses.js';

/**
 * @typedef {object} Driver
 * @property {string} key - short identifier (also the weights key).
 * @property {string} label - human-readable name for the UI.
 * @property {string} normKey - the sector property holding this driver's 0..1 value.
 */

/** The four blendable drivers, in canonical UI order. @type {Driver[]} */
export const DRIVERS = [
  { key: 'traffic', label: 'Foot-traffic', normKey: 'traffic_norm' },
  { key: 'residential', label: 'Residents', normKey: 'residential_norm' },
  { key: 'income', label: 'Income', normKey: 'income_norm' },
  { key: 'transit', label: 'Transit', normKey: 'transit_norm' },
];

/** The default blend: use the precomputed opportunity score. */
export const defaultBlend = { mode: 'default' };

/**
 * Named blend presets. Each value is a blend object.
 * Use presetBlend(name) to get a fresh (non-shared) copy.
 */
export const PRESETS = {
  default: { mode: 'default' },
  balanced: {
    mode: 'custom',
    weights: { traffic: 1, residential: 1, income: 1, transit: 1 },
  },
  footfall: {
    mode: 'custom',
    weights: { traffic: 0.55, residential: 0.2, income: 0.15, transit: 0.1 },
  },
  residential: {
    mode: 'custom',
    weights: { traffic: 0.15, residential: 0.55, income: 0.2, transit: 0.1 },
  },
  affluence: {
    mode: 'custom',
    weights: { traffic: 0.2, residential: 0.15, income: 0.55, transit: 0.1 },
  },
};

/**
 * Return a fresh deep copy of a named preset's blend object.
 *
 * @param {string} name - a key of PRESETS.
 * @returns {object} a new blend object (defaults to {mode:'default'} if unknown).
 */
export function presetBlend(name) {
  const preset = PRESETS[name];
  if (!preset) return { mode: 'default' };
  if (preset.mode === 'custom') {
    return { mode: 'custom', weights: { ...preset.weights } };
  }
  return { mode: preset.mode };
}

// Safely coerce a possibly-null/undefined value to a finite number (default 0).
function num(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Compute the score for one sector.
 *
 * @param {object} props - the sector GeoJSON feature properties.
 * @param {('cafe'|'bakery'|'confectionery')} type - selected business type.
 * @param {object|null} lens - an active lens object (with coverageKey), or null.
 * @param {object} blend - a blend object ({mode:'default'} or custom).
 * @returns {number|null} the score, or null when the sector is not scorable.
 */
export function scoreFeature(props, type, lens, blend) {
  // Callers pass a lens SLUG (string) or an object; normalise to an object.
  const L = typeof lens === 'string' ? getLens(lens) : lens;
  const oppRaw = props ? props[`opp_${type}`] : null;
  // Never light up non-scorable sectors.
  if (oppRaw === null || oppRaw === undefined) return null;

  let base;
  if (!blend || blend.mode === 'default') {
    base = Number(oppRaw);
  } else {
    const weights = blend.weights || {};
    let weightSum = 0;
    let weighted = 0;
    for (const driver of DRIVERS) {
      const w = num(weights[driver.key]);
      weightSum += w;
      weighted += w * num(props[driver.normKey]);
    }
    // All-zero weights -> fall back to the precomputed opportunity score.
    base = weightSum > 0 ? weighted / weightSum : Number(oppRaw);
  }

  if (L) {
    base = base * (1 - num(props[L.coverageKey]));
  }

  return base;
}

/**
 * Build a MapLibre GL expression that yields the same value as scoreFeature,
 * WITHOUT the null-grey case (the Map tests ['get','opp_'+type] == null itself).
 *
 * @param {('cafe'|'bakery'|'confectionery')} type - selected business type.
 * @param {object|null} lens - an active lens object (with coverageKey), or null.
 * @param {object} blend - a blend object ({mode:'default'} or custom).
 * @returns {Array} a MapLibre GL expression.
 */
export function buildScoreExpression(type, lens, blend) {
  // Callers pass a lens SLUG (string) or an object; normalise to an object.
  const L = typeof lens === 'string' ? getLens(lens) : lens;
  let base;

  if (!blend || blend.mode === 'default') {
    base = ['get', `opp_${type}`];
  } else {
    const weights = blend.weights || {};
    let weightSum = 0;
    for (const driver of DRIVERS) {
      weightSum += num(weights[driver.key]);
    }

    if (weightSum > 0) {
      // Normalised weighted sum of the driver norm fields.
      const terms = ['+'];
      for (const driver of DRIVERS) {
        const w = num(weights[driver.key]) / weightSum;
        terms.push(['*', w, ['coalesce', ['get', driver.normKey], 0]]);
      }
      base = terms;
    } else {
      // All-zero weights -> fall back to the precomputed opportunity score.
      base = ['get', `opp_${type}`];
    }
  }

  if (L) {
    base = ['*', base, ['-', 1, ['coalesce', ['get', L.coverageKey], 0]]];
  }

  return base;
}
