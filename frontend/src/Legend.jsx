// Color-scale legend with a one-line onboarding hint and the honesty footnote.

import { TYPE_LABELS } from './explainer.js';
import { getLens } from './lenses.js';
import { rampCssGradient, NO_DATA_COLOR } from './colors.js';

export default function Legend({ type, lens, hasSelection }) {
  const label = TYPE_LABELS[type] || 'spot';
  const lensMeta = getLens(lens);

  return (
    <div className="legend">
      <div className="legend__head">
        <div className="legend__title">
          <span className="legend__eyebrow">Underserved demand</span>
          <strong className="legend__type">{label}</strong>
        </div>
        {lensMeta && <span className="legend__badge">{lensMeta.label} lens</span>}
      </div>

      <div className="legend__scale" aria-hidden="true">
        {/* Gradient comes from colors.js so the bar and the map ramp can't drift. */}
        <span className="legend__bar" style={{ background: rampCssGradient('90deg') }} />
      </div>
      <div className="legend__ticks">
        <span>Low</span>
        <span>Opportunity</span>
        <span>High</span>
      </div>

      <div className="legend__nodata">
        <span
          className="legend__nodata-swatch"
          style={{ background: NO_DATA_COLOR }}
          aria-hidden="true"
        />
        Too few establishments to score (greyed out)
      </div>

      {/* First-run discoverability nudge: shown until the user inspects a zone. */}
      {!hasSelection && (
        <p className="legend__hint">Click a zone on the map to inspect it.</p>
      )}

      <p className="legend__footnote">
        Traffic is a <strong>proxy</strong>; <code>diet:*</code> tags undercount.
        Signals, not guarantees.
      </p>
    </div>
  );
}
