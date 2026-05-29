import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import MapView from './Map.jsx';
import TypeSwitch from './TypeSwitch.jsx';
import LensSelect from './LensSelect.jsx';
import BlendControls from './BlendControls.jsx';
import TopZones from './TopZones.jsx';
import Compare from './Compare.jsx';
import Legend from './Legend.jsx';
import SpotPanel from './SpotPanel.jsx';
import CitySelect from './CitySelect.jsx';
import { getSpots, getPoints, getCities } from './api.js';
import { defaultBlend } from './blend.js';
import { encodeState, decodeState } from './sharestate.js';

const MAX_COMPARE = 3;

export default function App() {
  // App-owned state.
  const [type, setType] = useState('cafe');
  const [lens, setLens] = useState(null); // dietary lens slug | null
  const [blend, setBlend] = useState(defaultBlend);
  const [aiMode, setAiMode] = useState(false); // AI mode defaults OFF.
  const [selected, setSelected] = useState(null); // selected sector (unit) properties
  const [compare, setCompare] = useState([]); // array of feature.properties (max 3)
  const [focus, setFocus] = useState(null); // { center:[lon,lat], zoom? }
  const [cities, setCities] = useState([]);
  const [city, setCity] = useState('antwerpen');
  // Mobile-only Filters drawer. Default closed so the map is visible on first
  // paint on a phone; on desktop the .controls__body is always shown via CSS
  // (the media query that hides it never matches), so this stays inert there.
  const [filtersOpen, setFiltersOpen] = useState(false);

  // Data lifecycle.
  const [data, setData] = useState(null);
  const [points, setPoints] = useState(null); // points FeatureCollection | null
  const [status, setStatus] = useState('loading'); // 'loading' | 'ready' | 'error'
  const [error, setError] = useState('');

  // Share-link feedback.
  const [shareCopied, setShareCopied] = useState(false);

  // Pending selection/compare from a shared URL, applied once data arrives.
  const pendingRef = useRef({ sel: null, cmp: null });
  // Guard so the first hash-sync effect doesn't clobber the decoded hash before
  // the deep-linked selection has had a chance to apply.
  const hashReadyRef = useRef(false);

  const load = useCallback(async (citySlug) => {
    setStatus('loading');
    setError('');
    try {
      const fc = await getSpots(citySlug);
      setData(fc);
      setStatus('ready');
    } catch (err) {
      setError(err?.message || 'Something went wrong loading the map data.');
      setStatus('error');
    }
    // Points are a best-effort, independent fetch — never block the map.
    try {
      const pts = await getPoints(citySlug);
      setPoints(pts);
    } catch {
      setPoints(null);
    }
  }, []);

  // On mount: decode any shared URL state, discover cities, then load.
  useEffect(() => {
    let active = true;

    // Defensive decode of the URL hash (never throws).
    let seed = {};
    try {
      seed = decodeState(window.location.hash.replace(/^#/, ''));
    } catch {
      seed = {};
    }

    if (seed.type) setType(seed.type);
    if (seed.lens) setLens(seed.lens);
    if (seed.blend) setBlend(seed.blend);
    pendingRef.current = {
      sel: seed.sel || null,
      cmp: Array.isArray(seed.cmp) ? seed.cmp : null,
    };

    getCities()
      .then((res) => {
        if (!active) return;
        const list = res.cities || [];
        const fallback = res.default || (list[0] && list[0].slug) || 'antwerpen';
        // A city from the shared link wins if it's a known city.
        const initial =
          seed.city && list.some((c) => c.slug === seed.city) ? seed.city : fallback;
        setCities(list);
        setCity(initial);
        load(initial);
      })
      .catch(() => {
        if (!active) return;
        const initial = seed.city || 'antwerpen';
        setCity(initial);
        load(initial); // fallback if /api/cities is unavailable
      });

    return () => {
      active = false;
    };
  }, [load]);

  // When data arrives, apply any pending deep-linked selection / compare.
  useEffect(() => {
    if (!data || !Array.isArray(data.features)) return;
    const pending = pendingRef.current;
    if (!pending) return;

    if (pending.sel) {
      const feat = data.features.find(
        (f) => f.properties && String(f.properties.unit_id) === String(pending.sel),
      );
      if (feat) setSelected(feat.properties);
    }

    if (pending.cmp && pending.cmp.length) {
      const wanted = pending.cmp.map(String);
      const propsList = [];
      for (const f of data.features) {
        const p = f.properties;
        if (p && wanted.includes(String(p.unit_id))) propsList.push(p);
        if (propsList.length >= MAX_COMPARE) break;
      }
      if (propsList.length) setCompare(propsList);
    }

    // Consume the pending state once and mark the hash safe to overwrite.
    pendingRef.current = null;
    hashReadyRef.current = true;
  }, [data]);

  const onCity = useCallback(
    (slug) => {
      setCity(slug);
      setSelected(null);
      setCompare([]);
      setPoints(null);
      load(slug);
    },
    [load],
  );

  // Compare handlers (max 3, dedup by unit_id).
  const addCompare = useCallback((props) => {
    if (!props || props.unit_id == null) return;
    setCompare((prev) => {
      if (prev.some((p) => p.unit_id === props.unit_id)) return prev;
      if (prev.length >= MAX_COMPARE) return prev;
      return [...prev, props];
    });
  }, []);

  const removeCompare = useCallback((id) => {
    setCompare((prev) => prev.filter((p) => p.unit_id !== id));
  }, []);

  const clearCompare = useCallback(() => setCompare([]), []);

  const cityView = cities.find((c) => c.slug === city) || null;
  const selectedId = selected ? selected.unit_id : null;
  const compareIds = useMemo(() => compare.map((p) => p.unit_id), [compare]);

  // Establishments inside the selected sector: keep both the raw features (for
  // the map/minimap, which need geometry) and just the properties (for the list).
  const selectedPointFeatures = useMemo(() => {
    if (!selected || !points || !Array.isArray(points.features)) return [];
    return points.features.filter(
      (f) => f.properties && f.properties.unit_id === selected.unit_id,
    );
  }, [selected, points]);

  const selectedPointProps = useMemo(
    () => selectedPointFeatures.map((f) => f.properties),
    [selectedPointFeatures],
  );

  // Keep the URL hash in sync with the shareable state (debounced).
  useEffect(() => {
    if (!hashReadyRef.current) return;
    const handle = setTimeout(() => {
      try {
        const hash = encodeState({
          city,
          type,
          lens,
          blend,
          sel: selectedId,
          cmp: compareIds,
        });
        const url = `${window.location.pathname}${window.location.search}${hash ? `#${hash}` : ''}`;
        window.history.replaceState(null, '', url);
      } catch {
        /* never break the app over URL bookkeeping */
      }
    }, 250);
    return () => clearTimeout(handle);
  }, [city, type, lens, blend, selectedId, compareIds]);

  const onShare = useCallback(() => {
    const href = window.location.href;
    const done = () => {
      setShareCopied(true);
      setTimeout(() => setShareCopied(false), 1800);
    };
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(href).then(done).catch(() => fallbackCopy(href, done));
      } else {
        fallbackCopy(href, done);
      }
    } catch {
      fallbackCopy(href, done);
    }
  }, []);

  return (
    <div className="app">
      {/* Map fills the viewport beneath the overlays. */}
      <MapView
        data={data}
        type={type}
        lens={lens}
        blend={blend}
        selectedId={selectedId}
        selectedPoints={selectedPointFeatures}
        view={cityView}
        focus={focus}
        onSelect={setSelected}
      />

      {/* Top-left brand + controls overlay. The brand bar is always visible;
          on mobile the rest collapses behind the Filters toggle (default
          closed) so the map shows on first paint. On desktop the toggle is
          hidden and .controls__body always renders. */}
      <div className={`controls ${filtersOpen ? 'is-open' : ''}`}>
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">📍</span>
          <div className="brand__text">
            <span className="brand__name">SpotFinder</span>
            <span className="brand__sub">
              {(cityView && cityView.name) || 'Antwerp'} · underserved demand
            </span>
          </div>
          <button
            type="button"
            className="controls__toggle"
            aria-expanded={filtersOpen}
            aria-controls="controls-body"
            onClick={() => setFiltersOpen((v) => !v)}
          >
            {filtersOpen ? 'Done' : 'Filters'}
          </button>
          <button
            type="button"
            className="share-btn"
            onClick={onShare}
            title="Copy a shareable link to this view"
            aria-label="Copy a shareable link to this view"
          >
            {shareCopied ? 'Link copied' : 'Share'}
          </button>
        </div>

        <div className="controls__body" id="controls-body">
          <CitySelect cities={cities} city={city} onChange={onCity} />
          <TypeSwitch type={type} onChange={setType} />
          <LensSelect lens={lens} onChange={setLens} />
          <BlendControls blend={blend} onChange={setBlend} />

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
      </div>

      {/* Legend overlay (bottom-left). */}
      {status === 'ready' && <Legend type={type} lens={lens} />}

      {/* Top opportunities leaderboard (bottom-right). */}
      {status === 'ready' && (
        <TopZones
          data={data}
          type={type}
          lens={lens}
          blend={blend}
          selectedId={selectedId}
          onSelect={setSelected}
          onFocus={(center) => setFocus({ center })}
          onCompareAdd={addCompare}
        />
      )}

      {/* Compare bottom sheet. */}
      {compare.length > 0 && (
        <Compare
          items={compare}
          type={type}
          lens={lens}
          blend={blend}
          onRemove={removeCompare}
          onClear={clearCompare}
          onClose={clearCompare}
        />
      )}

      {/* Inspect panel. */}
      {selected && (
        <SpotPanel
          props={selected}
          type={type}
          lens={lens}
          aiMode={aiMode}
          selectedPointProps={selectedPointProps}
          selectedPointFeatures={selectedPointFeatures}
          features={data ? data.features : null}
          selectedId={selectedId}
          onCompareAdd={addCompare}
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
            <button type="button" className="overlay__retry" onClick={() => load(city)}>
              Retry
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Clipboard fallback for browsers without the async clipboard API (or when it
// is blocked). Uses a hidden textarea + execCommand('copy').
function fallbackCopy(text, done) {
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'absolute';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    if (done) done();
  } catch {
    /* give up silently — copying is a convenience, not critical */
  }
}
