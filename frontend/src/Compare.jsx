// Compare bottom sheet. Stacks up to three picked sectors side by side so you
// can read their opportunity, drivers and competition at a glance. Pure
// presentational — every value comes through props, and scoring is delegated to
// blend.js so the table always agrees with the choropleth.

import { scoreFeature, DRIVERS } from './blend.js';
import { getLens } from './lenses.js';

// Index of the best (winning) value in a list, given a comparison that returns
// true when `a` beats `b`. Skips null/undefined values. Returns -1 if nothing
// is comparable.
function bestIndex(values, beats) {
  let best = -1;
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    if (v == null || Number.isNaN(v)) continue;
    if (best === -1 || beats(v, values[best])) best = i;
  }
  return best;
}

export default function Compare({
  items,
  type,
  lens,
  blend,
  onRemove,
  onClear,
  onClose,
}) {
  if (!items || items.length === 0) return null;

  const lensMeta = lens ? getLens(lens) : null;

  // Opportunity (0..100, higher is better).
  const oppValues = items.map((props) => {
    const s = scoreFeature(props, type, lens, blend);
    return s == null ? null : Math.round(s * 100);
  });
  const oppBest = bestIndex(oppValues, (a, b) => a > b);

  // Driver rows (0..100, higher is better).
  const driverRows = DRIVERS.map((driver) => {
    const values = items.map((props) => {
      const raw = props[driver.normKey];
      return raw == null ? null : Math.round(Number(raw) * 100);
    });
    return {
      key: driver.key,
      label: driver.label,
      values,
      best: bestIndex(values, (a, b) => a > b),
    };
  });

  // Nearest <type>: bigger gap means more underserved, so bigger is better.
  const gapValues = items.map((props) => {
    const raw = props['gap_' + type];
    return raw == null ? null : Math.round(Number(raw));
  });
  const gapBest = bestIndex(gapValues, (a, b) => a > b);

  // Competitors: fewer is better.
  const compValues = items.map((props) => {
    const raw = props['comp_' + type];
    return raw == null ? null : Number(raw);
  });
  const compBest = bestIndex(compValues, (a, b) => a < b);

  // Lens coverage (0..100), only shown when a lens is active. Not scored for a
  // winner — coverage is a documented-coverage signal, not a ranking.
  const coverageValues = lensMeta
    ? items.map((props) => {
        const raw = props[lensMeta.coverageKey];
        return raw == null ? null : Math.round(Number(raw) * 100);
      })
    : null;

  return (
    <section className="compare" aria-label="Compare sectors">
      <header className="compare__header">
        <h2 className="compare__title">Compare sectors</h2>
        <div className="compare__actions">
          <button
            type="button"
            className="compare__clear"
            onClick={onClear}
          >
            Clear all
          </button>
          <button
            type="button"
            className="compare__close"
            aria-label="Close compare"
            onClick={onClose}
          >
            ×
          </button>
        </div>
      </header>

      <div className="compare__scroll">
      <table className="compare__table">
        <thead>
          <tr>
            <th scope="col" />
            {items.map((props) => (
              <th key={props.unit_id} scope="col">
                <span className="compare__unit">{props.unit_id}</span>
                <button
                  type="button"
                  className="compare__remove"
                  aria-label={`Remove ${props.unit_id}`}
                  onClick={() => onRemove(props.unit_id)}
                >
                  ×
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Opportunity</th>
            {oppValues.map((value, i) => (
              <td
                key={items[i].unit_id}
                className={i === oppBest ? 'is-best' : ''}
              >
                {value == null ? '—' : value}
              </td>
            ))}
          </tr>

          {driverRows.map((row) => (
            <tr key={row.key}>
              <th scope="row">{row.label}</th>
              {row.values.map((value, i) => (
                <td
                  key={items[i].unit_id}
                  className={i === row.best ? 'is-best' : ''}
                >
                  {value == null ? '—' : value}
                </td>
              ))}
            </tr>
          ))}

          <tr>
            <th scope="row">Nearest {type}</th>
            {gapValues.map((value, i) => (
              <td
                key={items[i].unit_id}
                className={i === gapBest ? 'is-best' : ''}
              >
                {value == null ? '—' : `${value} m`}
              </td>
            ))}
          </tr>

          <tr>
            <th scope="row">Competitors</th>
            {compValues.map((value, i) => (
              <td
                key={items[i].unit_id}
                className={i === compBest ? 'is-best' : ''}
              >
                {value == null ? '—' : value}
              </td>
            ))}
          </tr>

          {lensMeta && coverageValues && (
            <tr>
              <th scope="row">{lensMeta.label} coverage</th>
              {coverageValues.map((value, i) => (
                <td key={items[i].unit_id}>
                  {value == null ? '—' : `${value}%`}
                </td>
              ))}
            </tr>
          )}
        </tbody>
      </table>
      </div>
    </section>
  );
}
