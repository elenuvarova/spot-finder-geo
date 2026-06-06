// Dietary-lens selector. Picking a lens reweighs the choropleth by documented
// diet coverage across an area's eateries — surfacing zones where listed
// supply for that diet is thin. The empty option means "no lens".

import { useState } from 'react';
import { LENSES } from './lenses.js';

export default function LensSelect({ lens, onChange }) {
  const active = LENSES.find((l) => l.slug === lens) || null;
  const [info, setInfo] = useState(false);

  return (
    <div className="lens-select">
      <div className="lens-select__head">
        <label className="lens-select__label" htmlFor="lens-select-control">
          Dietary lens
        </label>
        <button
          type="button"
          className="blend__info-btn"
          aria-expanded={info}
          aria-label="What is the dietary lens?"
          title="What is the dietary lens?"
          onClick={() => setInfo((v) => !v)}
        >
          i
        </button>
      </div>

      {info && (
        <p className="blend__info">
          A lens re-ranks the map by how well an area&apos;s eateries already cover a
          diet, surfacing zones where <strong>documented</strong> supply is thin. It
          reads the <code>diet:*</code> OpenStreetMap tags, which undercount reality,
          so treat it as a signal, not a census.
        </p>
      )}

      <select
        id="lens-select-control"
        className="lens-select__control"
        value={lens || ''}
        onChange={(e) => onChange(e.target.value ? e.target.value : null)}
      >
        <option value="">None</option>
        {LENSES.map((l) => (
          <option key={l.slug} value={l.slug}>
            {l.emoji} {l.label}
          </option>
        ))}
      </select>
      <p className="lens-select__note">
        Re-ranks by <em>documented</em> diet coverage — the{' '}
        {active ? <code>{active.tag}</code> : <code>diet:*</code>} tag undercounts
        reality.
      </p>
    </div>
  );
}
