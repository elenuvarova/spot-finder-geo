// Dietary-lens selector. Picking a lens reweighs the choropleth by documented
// diet coverage across an area's eateries — surfacing zones where listed
// supply for that diet is thin. The empty option means "no lens".

import { LENSES } from './lenses.js';

export default function LensSelect({ lens, onChange }) {
  const active = LENSES.find((l) => l.slug === lens) || null;

  return (
    <div className="lens-select">
      <label className="lens-select__label" htmlFor="lens-select-control">
        Dietary lens
      </label>
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
