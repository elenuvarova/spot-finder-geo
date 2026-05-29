// Layer-1 template explainer.
//
// These rules MUST stay identical to backend/explain.py. They are the offline,
// always-available explanation that the UI shows immediately. When AI mode is on
// the backend may replace the text, but this template is the dependable fallback.

import { getLens } from './lenses.js';

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

// Lens note (BYTE-IDENTICAL to backend/explain.py and the SHARED CONTRACT).
// Fires only when a lens is active AND that lens' coverage is exactly 0.
function lensNote(lensMeta) {
  return (
    ' No ' +
    lensMeta.noteLabel +
    ' offering is documented among the eateries here yet (the ' +
    lensMeta.tag +
    ' tag undercounts reality).'
  );
}

// Generic, type-aware "go and look" prompt. Mirror these in backend/explain.py.
const ON_GROUND = {
  cafe: ' On the ground, check: peak-hour foot-traffic and how easy it is to reach on foot or transit.',
  bakery:
    ' On the ground, check: morning footfall from nearby homes and how far people already walk for fresh bread.',
  confectionery:
    ' On the ground, check: who walks past, local spending power, and how the nearest competitors price and present themselves.',
};

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
 * @param {string|null} lens - the active lens slug, or null for no lens.
 * @param {object} props - the hex GeoJSON feature properties.
 * @returns {string} a 2-3 sentence explanation ending with the signals caveat.
 */
export function explainTemplate(type, lens, props = {}) {
  const label = TYPE_LABELS[type] || TYPE_LABELS.cafe;

  // gap_T / comp_T are the fields for the selected type.
  const gapT = roundM(props[`gap_${type}`]);
  const compT = num(props[`comp_${type}`]);

  const residentialNorm = num(props.residential_norm);
  const incomeNorm = num(props.income_norm);
  const trafficNorm = num(props.traffic_norm);
  const lensMeta = getLens(lens);
  const coverage = lensMeta ? num(props[lensMeta.coverageKey]) : 0;

  // Reusable rule clauses (byte-identical to backend/explain.py).
  const crowded = `This zone is already crowded with ${label} competitors — higher risk.`;
  const catchmentGap = `Residential area and the nearest ${label} is roughly ${gapT}m away — a classic catchment gap.`;
  const affluentTraffic = `Affluent foot-traffic with limited supply here — a strong signal for a ${label}.`;
  const movement = `Plenty of movement and few ${label} competitors nearby.`;
  const weak = `Demand signals here are weak — a lower-potential zone for a ${label}.`;

  let sentence;

  // Saturation is the dominant risk for every type, so it leads when present.
  // Otherwise lead with the driver that matters most for this type:
  //   bakery -> residential + proximity gap, cafe -> traffic/transit,
  //   confectionery -> income (affluent foot-traffic).
  if (compT >= COMP_HIGH) {
    sentence = crowded;
  } else if (type === 'bakery') {
    if (gapT >= GAP_HIGH_M && residentialNorm >= HIGH) {
      sentence = catchmentGap;
    } else if (incomeNorm >= HIGH && trafficNorm >= HIGH) {
      sentence = affluentTraffic;
    } else if (trafficNorm >= HIGH) {
      sentence = movement;
    } else {
      sentence = weak;
    }
  } else if (type === 'confectionery') {
    if (incomeNorm >= HIGH && trafficNorm >= HIGH) {
      sentence = affluentTraffic;
    } else if (gapT >= GAP_HIGH_M && residentialNorm >= HIGH) {
      sentence = catchmentGap;
    } else if (trafficNorm >= HIGH) {
      sentence = movement;
    } else {
      sentence = weak;
    }
  } else {
    // cafe (and any unknown type) -> traffic/transit first
    if (trafficNorm >= HIGH && incomeNorm >= HIGH) {
      sentence = affluentTraffic;
    } else if (trafficNorm >= HIGH) {
      sentence = movement;
    } else if (gapT >= GAP_HIGH_M && residentialNorm >= HIGH) {
      sentence = catchmentGap;
    } else {
      sentence = weak;
    }
  }

  // Only when a lens is active AND there is genuinely NO documented offering for
  // it (not merely "low"), so the note stops firing on nearly every sector.
  if (lensMeta && coverage === 0) {
    sentence += lensNote(lensMeta);
  }

  sentence += ON_GROUND[type] || ON_GROUND.cafe;
  sentence += SIGNALS_CAVEAT;

  return sentence;
}
