import { useEffect, useState } from 'react';
import { explainTemplate, TYPE_LABELS } from './explainer.js';
import { explain as explainApi } from './api.js';

// Format a 0..1 opportunity index as a percentage, or an em-dash when null.
function fmtIndex(value) {
  if (value === null || value === undefined) return '—';
  return `${Math.round(Number(value) * 100)}`;
}

// Format a 0..1 normalized field as a compact 0-100 score.
function fmtNorm(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `${Math.round(n * 100)}`;
}

function fmtMeters(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `${Math.round(n)} m`;
}

function fmtPct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `${Math.round(n * 100)}%`;
}

function fmtInt(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `${Math.round(n)}`;
}

// Type-adaptive ordering/labels for the key inputs.
// Bakery emphasizes residential & proximity; cafe emphasizes traffic.
function keyInputs(type, props) {
  const traffic = {
    key: 'traffic',
    label: 'Foot-traffic (proxy)',
    value: fmtNorm(props.traffic_norm),
    suffix: '/100',
  };
  const residential = {
    key: 'residential',
    label: 'Residential density',
    value: fmtNorm(props.residential_norm),
    suffix: '/100',
  };
  const income = {
    key: 'income',
    label: 'Income level',
    value: fmtNorm(props.income_norm),
    suffix: '/100',
  };
  const transit = {
    key: 'transit',
    label: 'Transit access',
    value: fmtNorm(props.transit_norm),
    suffix: '/100',
  };
  const proximity = {
    key: 'proximity',
    label: `Nearest ${TYPE_LABELS[type] || 'spot'}`,
    value: fmtMeters(props[`gap_${type}`]),
    suffix: '',
  };

  if (type === 'bakery' || type === 'confectionery') {
    // Residential & proximity lead for neighborhood-driven types.
    return [residential, proximity, traffic, income, transit];
  }
  // Cafe: traffic leads.
  return [traffic, proximity, income, residential, transit];
}

export default function SpotPanel({ props, type, vegan, aiMode, onClose }) {
  // Always compute the local template text first.
  const template = props ? explainTemplate(type, vegan, props) : '';

  const [explanation, setExplanation] = useState(template);
  const [source, setSource] = useState('template');
  const [aiLoading, setAiLoading] = useState(false);

  // Recompute template + (optionally) request AI whenever the inputs change.
  useEffect(() => {
    if (!props) return;

    const local = explainTemplate(type, vegan, props);
    // Show the template IMMEDIATELY.
    setExplanation(local);
    setSource('template');
    setAiLoading(false);

    if (!aiMode) return;

    let cancelled = false;
    setAiLoading(true);

    explainApi({ type, vegan, props })
      .then((res) => {
        if (cancelled) return;
        // Replace text only when AI text arrives; keep template otherwise.
        if (res && typeof res.explanation === 'string' && res.explanation.trim()) {
          setExplanation(res.explanation);
          setSource(res.source === 'ai' ? 'ai' : 'template');
        }
      })
      .catch(() => {
        // On any failure keep the template text already shown.
        if (cancelled) return;
        setSource('template');
      })
      .finally(() => {
        if (!cancelled) setAiLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [props, type, vegan, aiMode]);

  if (!props) return null;

  const label = TYPE_LABELS[type] || 'spot';
  const oppValue = props[`opp_${type}`];
  const oppNull = oppValue === null || oppValue === undefined;
  const inputs = keyInputs(type, props);
  const comp = fmtInt(props[`comp_${type}`]);

  return (
    <aside className="panel" aria-label="Zone details">
      <header className="panel__header">
        <div>
          <div className="panel__eyebrow">{label} opportunity</div>
          <div className="panel__id">Hex {props.h3 || '—'}</div>
        </div>
        <button
          type="button"
          className="panel__close"
          onClick={onClose}
          aria-label="Close panel"
        >
          ×
        </button>
      </header>

      <div className="panel__index">
        {oppNull ? (
          <>
            <div className="panel__index-value panel__index-value--muted">—</div>
            <div className="panel__index-note">
              Too few food establishments here to score reliably.
            </div>
          </>
        ) : (
          <>
            <div className="panel__index-value">
              {fmtIndex(oppValue)}
              <span className="panel__index-unit">/100</span>
            </div>
            <div className="panel__index-note">
              Opportunity index for a {label}
              {vegan ? ' (vegan lens applied on the map)' : ''}.
            </div>
          </>
        )}
      </div>

      <section className="panel__section">
        <h3 className="panel__section-title">Key inputs</h3>
        <ul className="panel__metrics">
          {inputs.map((m) => (
            <li key={m.key} className="panel__metric">
              <span className="panel__metric-label">{m.label}</span>
              <span className="panel__metric-value">
                {m.value}
                {m.suffix && <span className="panel__metric-suffix">{m.suffix}</span>}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel__section">
        <h3 className="panel__section-title">Competition &amp; vegan</h3>
        <ul className="panel__metrics">
          <li className="panel__metric">
            <span className="panel__metric-label">{label} competitors (nearby)</span>
            <span className="panel__metric-value">{comp}</span>
          </li>
          <li className="panel__metric">
            <span className="panel__metric-label">Food establishments here</span>
            <span className="panel__metric-value">{fmtInt(props.n_food)}</span>
          </li>
          <li className="panel__metric">
            <span className="panel__metric-label">Documented vegan coverage</span>
            <span className="panel__metric-value">{fmtPct(props.vegan_coverage)}</span>
          </li>
        </ul>
      </section>

      <section className="panel__section panel__why">
        <div className="panel__why-head">
          <h3 className="panel__section-title">Why this zone?</h3>
          {aiMode && aiLoading && (
            <span className="panel__ai-status" aria-live="polite">
              <span className="panel__spinner" aria-hidden="true" /> thinking…
            </span>
          )}
          {source === 'ai' && !aiLoading && (
            <span className="panel__ai-badge" title="Written by the AI explainer">
              AI
            </span>
          )}
        </div>
        <p className="panel__why-text">{explanation}</p>
      </section>

      <p className="panel__disclaimer">
        These are <strong>signals, not guarantees</strong>. Foot-traffic is a
        weighted proxy and vegan figures come from the <code>diet:vegan</code> tag,
        which undercounts reality. Always check a site on foot.
      </p>
    </aside>
  );
}
