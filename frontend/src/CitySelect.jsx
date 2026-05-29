// City selector. Switching the city loads that city's GeoJSON and recenters
// the map. Hidden when the backend offers fewer than two cities.

export default function CitySelect({ cities, city, onChange }) {
  if (!cities || cities.length < 2) return null;
  return (
    <div className="city-select" role="group" aria-label="City">
      <span className="city-select__label">City</span>
      <div className="city-select__btns">
        {cities.map((c) => (
          <button
            key={c.slug}
            type="button"
            className={`city-select__btn ${city === c.slug ? 'is-active' : ''}`}
            aria-pressed={city === c.slug}
            onClick={() => onChange(c.slug)}
          >
            {c.name}
          </button>
        ))}
      </div>
    </div>
  );
}
