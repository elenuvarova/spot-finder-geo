// Shareable URL state — encode/decode the app's view into a compact hash string.
//
// The string is stored as the URL hash WITHOUT a leading '#'. It is intentionally
// terse and forgiving: decodeState never throws and silently drops anything it
// does not understand, so a hand-edited or stale link degrades gracefully.
//
// State shape: { city, type, lens, blend, sel, cmp }
//   city : string slug
//   type : 'cafe' | 'bakery' | 'confectionery'
//   lens : lens slug | null
//   blend: a blend object ({mode:'default'} | preset | {mode:'custom',weights})
//   sel  : a selected unit_id | null
//   cmp  : array of unit_id to compare
//
// Wire keys: c=city, t=type, l=lens, b=blend, s=sel, m=cmp.

import { PRESETS } from './blend.js';

// Reverse lookup: which PRESETS name corresponds to a given blend object?
// Used so a preset round-trips as 'p:NAME' rather than its raw weights.
function presetNameFor(blend) {
  if (!blend) return null;
  for (const name of Object.keys(PRESETS)) {
    const preset = PRESETS[name];
    if (preset.mode !== blend.mode) continue;
    if (blend.mode === 'default') return name;
    if (blend.mode === 'custom') {
      const a = preset.weights || {};
      const b = blend.weights || {};
      if (
        Number(a.traffic) === Number(b.traffic) &&
        Number(a.residential) === Number(b.residential) &&
        Number(a.income) === Number(b.income) &&
        Number(a.transit) === Number(b.transit)
      ) {
        return name;
      }
    }
  }
  return null;
}

// Encode a blend object to its wire form.
function encodeBlend(blend) {
  if (!blend || blend.mode === 'default') return 'd';

  const name = presetNameFor(blend);
  if (name && name !== 'default') return `p:${name}`;

  if (blend.mode === 'custom') {
    const w = blend.weights || {};
    const parts = [
      Number(w.traffic) || 0,
      Number(w.residential) || 0,
      Number(w.income) || 0,
      Number(w.transit) || 0,
    ];
    return `c:${parts.join(',')}`;
  }

  return 'd';
}

// Decode a blend wire form back to a blend object (defensive; never throws).
function decodeBlend(raw) {
  if (typeof raw !== 'string' || raw === '') return undefined;
  if (raw === 'd') return { mode: 'default' };

  if (raw.startsWith('p:')) {
    const name = raw.slice(2);
    return PRESETS[name] || { mode: 'default' };
  }

  if (raw.startsWith('c:')) {
    const nums = raw.slice(2).split(',').map(Number);
    const at = (i) => (Number.isFinite(nums[i]) && nums[i] >= 0 ? nums[i] : 0);
    return {
      mode: 'custom',
      weights: {
        traffic: at(0),
        residential: at(1),
        income: at(2),
        transit: at(3),
      },
    };
  }

  return undefined;
}

/**
 * Encode an app state object into a compact hash string (no leading '#').
 *
 * Only the keys that carry meaningful values are emitted.
 *
 * @param {object} state - { city, type, lens, blend, sel, cmp }.
 * @returns {string} a URL-safe hash payload.
 */
export function encodeState(state = {}) {
  const params = new URLSearchParams();

  if (state.city) params.set('c', String(state.city));
  if (state.type) params.set('t', String(state.type));
  if (state.lens) params.set('l', String(state.lens));
  if (state.blend) params.set('b', encodeBlend(state.blend));
  if (state.sel) params.set('s', String(state.sel));
  if (Array.isArray(state.cmp) && state.cmp.length) {
    // Join unit_ids; URLSearchParams encodes each value for us.
    params.set('m', state.cmp.map((id) => encodeURIComponent(String(id))).join(','));
  }

  return params.toString();
}

/**
 * Decode a hash string into a PARTIAL state object.
 *
 * Absent or invalid keys are omitted entirely (never set to null/undefined),
 * so callers can spread the result over their defaults. Never throws.
 *
 * @param {string} str - a hash payload (with or without a leading '#').
 * @returns {object} a partial { city?, type?, lens?, blend?, sel?, cmp? }.
 */
export function decodeState(str) {
  const out = {};
  if (typeof str !== 'string') return out;

  let params;
  try {
    params = new URLSearchParams(str.replace(/^#/, ''));
  } catch {
    return out;
  }

  const c = params.get('c');
  if (c) out.city = c;

  const t = params.get('t');
  if (t === 'cafe' || t === 'bakery' || t === 'confectionery') out.type = t;

  const l = params.get('l');
  if (l) out.lens = l;

  const b = params.get('b');
  const blend = decodeBlend(b);
  if (blend) out.blend = blend;

  const s = params.get('s');
  if (s) out.sel = s;

  const m = params.get('m');
  if (m) {
    const ids = m
      .split(',')
      .map((part) => {
        try {
          return decodeURIComponent(part);
        } catch {
          return part;
        }
      })
      .filter((id) => id !== '');
    if (ids.length) out.cmp = ids;
  }

  return out;
}
