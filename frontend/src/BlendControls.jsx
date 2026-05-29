// Scoring-blend controls. The "Default" preset uses SpotFinder's per-type
// opportunity model; the other presets and the custom sliders re-rank sectors
// by user-chosen driver weights. Pure presentational component — all state
// lives in the blend prop, owned by the parent.

import { useState } from 'react';
import { DRIVERS, PRESETS, presetBlend } from './blend.js';

// Preset buttons, in display order. Each maps to a key in PRESETS.
const PRESET_BUTTONS = [
  { key: 'default', label: 'Default' },
  { key: 'balanced', label: 'Balanced' },
  { key: 'footfall', label: 'Footfall' },
  { key: 'residential', label: 'Residents' },
  { key: 'affluence', label: 'Affluence' },
];

// Compare a blend object against a named preset to drive the is-active state.
function matchesPreset(blend, presetKey) {
  const preset = presetBlend(presetKey);
  if (!preset || !blend) return false;
  if (preset.mode !== blend.mode) return false;
  if (preset.mode === 'default') return true;
  // Custom: weights must match driver-for-driver.
  return DRIVERS.every(
    (d) => Number(preset.weights[d.key]) === Number(blend.weights[d.key])
  );
}

// Slider positions: read from custom weights when present, else a neutral 50.
function sliderValue(blend, key) {
  if (blend && blend.mode === 'custom' && blend.weights) {
    const v = Number(blend.weights[key]);
    return Number.isFinite(v) ? v : 50;
  }
  return 50;
}

export default function BlendControls({ blend, onChange }) {
  const [expanded, setExpanded] = useState(blend && blend.mode === 'custom');

  // Move one slider -> rebuild a full custom weights object from current values.
  function handleSlider(key, value) {
    const weights = {};
    DRIVERS.forEach((d) => {
      weights[d.key] = d.key === key ? Number(value) : sliderValue(blend, d.key);
    });
    onChange({ mode: 'custom', weights });
  }

  return (
    <div className="blend">
      <h3 className="blend__title">Scoring blend</h3>
      <p className="blend__lead">How sectors are ranked.</p>

      <div className="blend__presets" role="group" aria-label="Scoring presets">
        {PRESET_BUTTONS.map((p) => {
          const active = matchesPreset(blend, p.key);
          return (
            <button
              key={p.key}
              type="button"
              className={`blend__preset ${active ? 'is-active' : ''}`}
              aria-pressed={active}
              onClick={() => onChange(presetBlend(p.key))}
            >
              {p.label}
            </button>
          );
        })}
      </div>

      <button
        type="button"
        className="blend__customize"
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
      >
        Customize
      </button>

      {expanded && (
        <div className="blend__sliders">
          {DRIVERS.map((d) => {
            const value = sliderValue(blend, d.key);
            return (
              <label key={d.key} className="blend__slider">
                <span className="blend__slider-label">{d.label}</span>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={value}
                  aria-label={d.label}
                  onChange={(e) => handleSlider(d.key, e.target.value)}
                />
                <span className="blend__slider-value" aria-hidden="true">
                  {value}
                </span>
              </label>
            );
          })}
          <button
            type="button"
            className="blend__reset"
            onClick={() => onChange(presetBlend('default'))}
          >
            Reset to model
          </button>
          <p className="blend__note">
            Default uses SpotFinder's per-type model. Custom re-ranks by your own
            weights — your judgement, our data.
          </p>
        </div>
      )}
    </div>
  );
}
