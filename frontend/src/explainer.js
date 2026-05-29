// Layer-1 template explainer.
//
// These rules MUST stay identical to backend/explain.py. They are the offline,
// always-available explanation that the UI shows immediately. When AI mode is on
// the backend may replace the text, but this template is the dependable fallback.

// Thresholds (config). Mirror these in the backend.
export const HIGH = 0.6; // applies to the *_norm fields (0..1)
export const GAP_HIGH_M = 400; // meters; a "real" catchment gap
export const COMP_HIGH = 4; // competitor count considered crowded

// Human-readable labels per type.
export const TYPE_LABELS = {
  cafe: 'coffee shop',
  bakery: 'bakery',
  confectionery: 'confectionery',
};

const SIGNALS_CAVEAT = ' These are signals, not guarantees — worth checking on foot.';
const VEGAN_NOTE =
  ' There is almost no documented vegan offering nearby (the diet:vegan tag undercounts reality).';

// Safely coerce a possibly-null/undefined property to a number (default 0).
function num(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

// Round meters to a whole number for display.
function roundM(value) {
  return Math.round(num(value));
}

/**
 * Build the template explanation for a hex.
 *
 * @param {('cafe'|'bakery'|'confectionery')} type - selected business type.
 * @param {boolean} vegan - whether the vegan lens is active.
 * @param {object} props - the hex GeoJSON feature properties.
 * @returns {string} a 2-3 sentence explanation ending with the signals caveat.
 */
export function explainTemplate(type, vegan, props = {}) {
  const label = TYPE_LABELS[type] || TYPE_LABELS.cafe;

  // gap_T / comp_T are the fields for the selected type.
  const gapT = roundM(props[`gap_${type}`]);
  const compT = num(props[`comp_${type}`]);

  const residentialNorm = num(props.residential_norm);
  const incomeNorm = num(props.income_norm);
  const trafficNorm = num(props.traffic_norm);
  const veganCoverage = num(props.vegan_coverage);

  let sentence;

  // Evaluate in order; return the FIRST matching rule.
  if (gapT >= GAP_HIGH_M && residentialNorm >= HIGH) {
    sentence = `Residential area and the nearest ${label} is roughly ${gapT}m away — a classic catchment gap.`;
  } else if (compT >= COMP_HIGH) {
    sentence = `This zone is already crowded with ${label} competitors — higher risk.`;
  } else if (incomeNorm >= HIGH && trafficNorm >= HIGH) {
    sentence = `Affluent foot-traffic with limited supply here — a strong signal for a ${label}.`;
  } else if (trafficNorm >= HIGH && compT < COMP_HIGH) {
    sentence = `Plenty of movement and few ${label} competitors nearby.`;
  } else {
    sentence = `Demand signals here are weak — a lower-potential zone for a ${label}.`;
  }

  if (vegan && veganCoverage < 0.2) {
    sentence += VEGAN_NOTE;
  }

  sentence += SIGNALS_CAVEAT;

  return sentence;
}
