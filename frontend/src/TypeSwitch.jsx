// Business-type selector. Switching the type changes which opp_<type> field
// drives the choropleth fill.

const TYPES = [
  { id: 'cafe', emoji: '☕', label: 'Coffee' }, // ☕
  { id: 'bakery', emoji: '🥐', label: 'Bakery' }, // 🥖
  { id: 'confectionery', emoji: '🧁', label: 'Confectionery' }, // 🧁
];

export default function TypeSwitch({ type, onChange }) {
  return (
    <div className="type-switch" role="group" aria-label="Business type">
      {TYPES.map((t) => (
        <button
          key={t.id}
          type="button"
          className={`type-switch__btn ${type === t.id ? 'is-active' : ''}`}
          aria-pressed={type === t.id}
          onClick={() => onChange(t.id)}
        >
          <span className="type-switch__emoji" aria-hidden="true">
            {t.emoji}
          </span>
          <span className="type-switch__label">{t.label}</span>
        </button>
      ))}
    </div>
  );
}
