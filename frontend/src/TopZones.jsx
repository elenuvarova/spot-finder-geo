// Top opportunities leaderboard. Ranks the sectors with the highest blended
// opportunity score for the current type/lens/blend, so users can jump straight
// to the strongest signals instead of hunting on the map.
//
// Pure presentational: all data arrives via props; the only local state is
// whether the card is expanded. Scoring lives in blend.js (single source of
// truth) and centroids in geometry.js — we never recompute either here.

import { useState } from 'react';
import { scoreFeature } from './blend.js';
import { centroid } from './geometry.js';

const TOP_N = 10;

// Shorten a sector unit_id for the compact row. Many id schemes are
// prefixed/namespaced (e.g. "city:1234" or "a/b/1234"); show the last segment
// when that's the case, otherwise the id as-is.
function shortId(unitId) {
  if (unitId === null || unitId === undefined) return '—';
  const id = String(unitId);
  const parts = id.split(/[:/]/);
  return parts[parts.length - 1] || id;
}

export default function TopZones({
  data,
  type,
  lens,
  blend,
  selectedId,
  onSelect,
  onFocus,
  onCompareAdd,
}) {
  // Default expanded on desktop, collapsed on phones so the leaderboard never
  // pushes the page off-screen on first paint. matchMedia mirrors the CSS
  // breakpoint; the SSR-safe guard keeps it expanded if window is unavailable.
  const [expanded, setExpanded] = useState(
    () =>
      !(
        typeof window !== 'undefined' &&
        window.matchMedia &&
        window.matchMedia('(max-width: 720px)').matches
      ),
  );

  // Score every feature, drop the non-scorable (null) ones, sort descending.
  const ranked = [];
  if (data && Array.isArray(data.features)) {
    for (const feature of data.features) {
      const props = feature && feature.properties;
      if (!props) continue;
      const score = scoreFeature(props, type, lens, blend);
      if (score === null || score === undefined || !Number.isFinite(score)) {
        continue;
      }
      ranked.push({ feature, props, score });
    }
  }
  ranked.sort((a, b) => b.score - a.score);
  const top = ranked.slice(0, TOP_N);

  // Nothing scorable -> render nothing at all.
  if (top.length === 0) return null;

  // Bar widths are relative to the strongest score in the list, so the
  // leaderboard always shows a full bar at the top.
  const maxScore = top[0].score || 1;

  return (
    <div className={`top-zones${expanded ? ' is-open' : ''}`}>
      <button
        type="button"
        className="top-zones__toggle"
        aria-expanded={expanded}
        aria-label={expanded ? 'Collapse top opportunities' : 'Expand top opportunities'}
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="top-zones__title">
          Top opportunities
          <span className="top-zones__count">{top.length}</span>
        </span>
        <span className="top-zones__chevron" aria-hidden="true">
          {expanded ? '×' : '+'}
        </span>
      </button>

      {expanded && (
        <ol className="top-zones__list">
          {top.map((item, i) => {
            const { feature, props, score } = item;
            const isSelected = props.unit_id === selectedId;
            const pct = Math.max(0, Math.min(100, (score / maxScore) * 100));
            const select = () => {
              onSelect(props);
              onFocus(centroid(feature.geometry));
            };
            return (
              <li
                key={props.unit_id != null ? props.unit_id : i}
                className={`top-zones__item${isSelected ? ' is-selected' : ''}`}
                // Keyboard-operable selector: the row IS the control (the nested
                // "+ compare" is a separate button). role+tabIndex+Enter/Space
                // give keyboard users the same "inspect this sector" path the
                // map click gives mouse users. The e.target guard stops key
                // presses on the inner button from also selecting the row.
                role="button"
                tabIndex={0}
                aria-current={isSelected ? 'true' : undefined}
                aria-label={`Select sector ${props.unit_id ?? ''}, opportunity score ${Math.round(
                  score * 100,
                )} of 100`}
                onClick={select}
                onKeyDown={(e) => {
                  if (e.target !== e.currentTarget) return;
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    select();
                  }
                }}
              >
                <span className="top-zones__rank">{i + 1}</span>
                <span className="top-zones__sector" title={`Sector ${props.unit_id ?? ''}`}>
                  <span className="top-zones__sector-tag">Sector</span>{' '}
                  {shortId(props.unit_id)}
                </span>
                <span className="top-zones__bar">
                  <span style={{ width: pct + '%' }} />
                </span>
                <span className="top-zones__chip">{Math.round(score * 100)}</span>
                <button
                  type="button"
                  className="top-zones__cmp"
                  onClick={(e) => {
                    e.stopPropagation();
                    onCompareAdd(props);
                  }}
                >
                  + compare
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
