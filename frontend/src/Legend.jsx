// Color-scale legend with a one-line onboarding hint and the honesty footnote.

import { TYPE_LABELS } from './explainer.js';

export default function Legend({ type, vegan }) {
  const label = TYPE_LABELS[type] || 'spot';

  return (
    <div className="legend">
      <div className="legend__title">
        Underserved demand · <strong>{label}</strong>
        {vegan && <span className="legend__badge">vegan lens</span>}
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
        a sensor count. Vegan coverage uses the <code>diet:vegan</code> tag, which
        undercounts real availability. Signals, not guarantees.
      </p>
    </div>
  );
}
