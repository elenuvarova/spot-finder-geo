// Single source of truth for the opportunity color ramp and the shared map
// neutrals. The Map paint expressions, the SectorMiniMap SVG fills and the
// Legend gradient all read from here so they can never drift apart.
//
// Keep this in sync with the legend swatch tokens in styles.css that reference
// these same values (--map-* custom properties).

/**
 * The 5-stop opportunity ramp: red (low) -> green (high) across 0..1.
 * Each stop is { at: 0..1, color: '#rrggbb' } in ascending order.
 */
export const RAMP = [
  { at: 0.0, color: '#d73027' }, // red — low opportunity
  { at: 0.25, color: '#fc8d59' },
  { at: 0.5, color: '#fee08b' }, // amber — middling
  { at: 0.75, color: '#91cf60' },
  { at: 1.0, color: '#1a9850' }, // green — high opportunity
];

// Grey shown when a hex has no opportunity value (opp_<type> is null).
export const NO_DATA_COLOR = '#cfd3d8';

// Shared map neutrals used by the choropleth lines and the establishment dots.
export const SELECTED_OUTLINE = '#1f2933'; // selected-hex highlight stroke
export const EATERY_COLOR = '#1a7f56'; // establishment dot — eatery
export const NON_EATERY_COLOR = '#7b8794'; // establishment dot — non-eatery

// Mini-map (SVG) neutrals.
export const MINIMAP_SECTOR_FILL = '#eef1f3';
export const MINIMAP_SECTOR_STROKE = '#cbd2d9';
export const MINIMAP_SELECTED_FILL = 'rgba(26,127,86,0.85)';
export const MINIMAP_SELECTED_STROKE = '#0f5c3d';
export const MINIMAP_EATERY_DOT = '#0f5c3d';
export const MINIMAP_NON_EATERY_DOT = '#52606d';

/**
 * Flatten the ramp into the (value, color) pairs a MapLibre GL `interpolate`
 * expression expects: [0.0, '#...', 0.25, '#...', ...].
 *
 * @returns {Array} the interpolate stop pairs.
 */
export function rampInterpolateStops() {
  const stops = [];
  for (const stop of RAMP) {
    stops.push(stop.at, stop.color);
  }
  return stops;
}

/**
 * Build the CSS linear-gradient string for the legend bar from the same ramp.
 *
 * @param {string} [direction='90deg'] - the gradient direction.
 * @returns {string} a CSS linear-gradient() value.
 */
export function rampCssGradient(direction = '90deg') {
  const stops = RAMP.map((s) => `${s.color} ${Math.round(s.at * 100)}%`).join(', ');
  return `linear-gradient(${direction}, ${stops})`;
}
