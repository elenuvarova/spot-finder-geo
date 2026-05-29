// Diet lenses — the canonical list of dietary "lenses" the UI can apply.
//
// This list MUST stay in sync with backend/explain.py (the lens metadata) and is
// the single frontend source for lens slugs, labels, emojis, tags, the coverage
// property key each lens reads, and the human note label used in explanations.
//
// A lens === null everywhere in the app means "no lens" (raw opportunity).

/**
 * @typedef {object} Lens
 * @property {string} slug - stable identifier used in URL state and API calls.
 * @property {string} label - human-readable name for the UI.
 * @property {string} emoji - decorative glyph for the UI.
 * @property {string} tag - the OSM diet tag this lens is derived from.
 * @property {string} coverageKey - the sector property holding this lens' coverage (0..1).
 * @property {string} noteLabel - the word used in the lens note sentence.
 */

/** @type {Lens[]} */
export const LENSES = [
  {
    slug: 'vegan',
    label: 'Vegan',
    emoji: '🌱',
    tag: 'diet:vegan',
    coverageKey: 'vegan_coverage',
    noteLabel: 'vegan',
  },
  {
    slug: 'vegetarian',
    label: 'Vegetarian',
    emoji: '🥗',
    tag: 'diet:vegetarian',
    coverageKey: 'vegetarian_coverage',
    noteLabel: 'vegetarian',
  },
  {
    slug: 'glutenfree',
    label: 'Gluten-free',
    emoji: '🌾',
    tag: 'diet:gluten_free',
    coverageKey: 'glutenfree_coverage',
    noteLabel: 'gluten-free',
  },
  {
    slug: 'halal',
    label: 'Halal',
    emoji: '🕌',
    tag: 'diet:halal',
    coverageKey: 'halal_coverage',
    noteLabel: 'halal',
  },
];

/**
 * Resolve a lens by its slug.
 *
 * @param {string|null} slug - a lens slug, or null/unknown for "no lens".
 * @returns {Lens|null} the matching lens, or null when not found.
 */
export function getLens(slug) {
  return LENSES.find((l) => l.slug === slug) || null;
}
