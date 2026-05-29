// Color-scale legend with a one-line onboarding hint and the honesty footnote.

import { TYPE_LABELS } from './explainer.js';
import { getLens } from './lenses.js';

export default function Legend({ type, lens }) {
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
        <span className="legend__bar" />
      </div>
      <div className="legend__ticks">
        <span>Low</span>
        <span>Opportunity</span>
        <span>High</span>
      </div>

      <div className="legend__nodata">
        <span className="legend__nodata-swatch" aria-hidden="true" />
        Too few establishments to score (greyed out)
      </div>

      <p className="legend__hint">
        Tip: tap a neighbourhood to inspect the signals behind its score.
      </p>

      <p className="legend__footnote">
        Traffic is an honest <strong>proxy</strong> (weighted nearby points), not
        a sensor count. Diet coverage uses <code>diet:*</code> tags, which
        undercount real availability. Signals, not guarantees.
      </p>
    </div>
  );
}
