// Vegan lens toggle. When ON, the choropleth value becomes
// opp_<type> * (1 - vegan_coverage), surfacing zones where documented vegan
// supply is thin.

export default function VeganLens({ vegan, onChange }) {
  return (
    <div className="vegan-lens">
      <label className="vegan-lens__row">
        <input
          type="checkbox"
          checked={vegan}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span className="vegan-lens__switch" aria-hidden="true" />
        <span className="vegan-lens__text">
          <span className="vegan-lens__title">🌱 Vegan lens</span>
        </span>
      </label>
      <p className="vegan-lens__note">
        Weighs opportunity by <em>documented</em> <code>diet:vegan</code> coverage
        across the area's eateries (cafés, bakeries, restaurants…). The tag
        undercounts reality — a "gap" means no <strong>listed</strong> vegan
        offering, not that there is no vegan food.
      </p>
    </div>
  );
}
