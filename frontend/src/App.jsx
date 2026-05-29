import { useCallback, useEffect, useState } from 'react';
import MapView from './Map.jsx';
import TypeSwitch from './TypeSwitch.jsx';
import VeganLens from './VeganLens.jsx';
import Legend from './Legend.jsx';
import SpotPanel from './SpotPanel.jsx';
import { getSpots } from './api.js';

export default function App() {
  // App-owned state.
  const [type, setType] = useState('cafe');
  const [vegan, setVegan] = useState(false);
  const [aiMode, setAiMode] = useState(false); // AI mode defaults OFF.
  const [selected, setSelected] = useState(null); // selected hex properties

  // Data lifecycle.
  const [data, setData] = useState(null);
  const [status, setStatus] = useState('loading'); // 'loading' | 'ready' | 'error'
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setStatus('loading');
    setError('');
    try {
      const fc = await getSpots();
      setData(fc);
      setStatus('ready');
    } catch (err) {
      setError(err?.message || 'Something went wrong loading the map data.');
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const selectedH3 = selected ? selected.h3 : null;

  return (
    <div className="app">
      {/* Map fills the viewport beneath the overlays. */}
      <MapView
        data={data}
        type={type}
        vegan={vegan}
        selectedH3={selectedH3}
        onSelect={setSelected}
      />

      {/* Top-left brand + controls overlay. */}
      <div className="controls">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">📍</span>
          <div className="brand__text">
            <span className="brand__name">SpotFinder</span>
            <span className="brand__sub">Antwerp · underserved demand</span>
          </div>
        </div>

        <TypeSwitch type={type} onChange={setType} />
        <VeganLens vegan={vegan} onChange={setVegan} />

        <label className="ai-toggle">
          <input
            type="checkbox"
            checked={aiMode}
            onChange={(e) => setAiMode(e.target.checked)}
          />
          <span className="ai-toggle__switch" aria-hidden="true" />
          <span className="ai-toggle__text">
            ✨ AI explanations
            <span className="ai-toggle__hint">template always works offline</span>
          </span>
        </label>
      </div>

      {/* Legend overlay (bottom-left). */}
      {status === 'ready' && <Legend type={type} vegan={vegan} />}

      {/* Inspect panel. */}
      {selected && (
        <SpotPanel
          props={selected}
          type={type}
          vegan={vegan}
          aiMode={aiMode}
          onClose={() => setSelected(null)}
        />
      )}

      {/* Loading overlay — never a blank white screen during cold start. */}
      {status === 'loading' && (
        <div className="overlay" role="status" aria-live="polite">
          <div className="overlay__card">
            <span className="overlay__spinner" aria-hidden="true" />
            <h2 className="overlay__title">Loading Antwerp…</h2>
            <p className="overlay__text">
              Fetching demand signals. The backend may be waking up from sleep —
              this can take 30-50 seconds on the first request.
            </p>
          </div>
        </div>
      )}

      {/* Error overlay with retry. */}
      {status === 'error' && (
        <div className="overlay" role="alert">
          <div className="overlay__card">
            <h2 className="overlay__title">Couldn’t load the map</h2>
            <p className="overlay__text">{error}</p>
            <button type="button" className="overlay__retry" onClick={load}>
              Retry
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
