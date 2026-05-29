// Tiny vector locator for the selected sector. Prints crisply: no map tiles,
// no external requests — just an inline <svg> drawn from the GeoJSON we already
// have. Shown in the panel and in print.

import { bounds } from './geometry.js';

const VIEW_W = 200; // viewBox units; height derives from the data aspect ratio.
const PAD = 6; // padding inside the viewBox, in the same units.

// Outer rings for a feature, handling Polygon and MultiPolygon.
function outerRings(geometry) {
  if (!geometry) return [];
  if (geometry.type === 'Polygon') {
    return geometry.coordinates[0] ? [geometry.coordinates[0]] : [];
  }
  if (geometry.type === 'MultiPolygon') {
    return geometry.coordinates
      .map((poly) => poly[0])
      .filter(Boolean);
  }
  return [];
}

export default function SectorMiniMap({ features, selectedId, points }) {
  if (!features || features.length === 0) return null;

  const selected = features.find(
    (f) => f.properties && f.properties.unit_id === selectedId
  );
  if (!selected) return null;

  // bounds() returns [[minLon, minLat], [maxLon, maxLat]] over every sector.
  const box = bounds(features);
  if (!box || box.length < 2 || !box[0] || !box[1]) return null;
  const [[minLon, minLat], [maxLon, maxLat]] = box;
  const lonSpan = maxLon - minLon;
  const latSpan = maxLat - minLat;
  if (!(lonSpan > 0) || !(latSpan > 0)) return null;

  // Counter the horizontal squish away from the equator.
  const meanLat = (minLat + maxLat) / 2;
  const lonScale = Math.cos((meanLat * Math.PI) / 180) || 1;
  const geoW = lonSpan * lonScale;
  const geoH = latSpan;

  // Fit the data box into a drawable area of fixed width, height from aspect.
  const drawW = VIEW_W - PAD * 2;
  const drawH = drawW * (geoH / geoW);
  const viewH = drawH + PAD * 2;

  const project = ([lon, lat]) => {
    const x = PAD + ((lon - minLon) * lonScale * drawW) / geoW;
    // Flip y so north is up.
    const y = PAD + drawH - ((lat - minLat) * drawH) / geoH;
    return [x, y];
  };

  const ringToPath = (ring) => {
    let d = '';
    for (let i = 0; i < ring.length; i += 1) {
      const [x, y] = project(ring[i]);
      d += `${i === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)} `;
    }
    return `${d}Z`;
  };

  const featurePath = (feature) =>
    outerRings(feature.geometry).map(ringToPath).join(' ');

  const pts = Array.isArray(points) ? points : [];

  return (
    <div className="sector-minimap">
      <svg
        viewBox={`0 0 ${VIEW_W} ${viewH.toFixed(2)}`}
        width="100%"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`Locator map for sector ${selectedId}`}
      >
        {/* Every sector: light fill + faint stroke so the surrounding fabric
            reads on screen (print CSS flattens these to white-on-grey). */}
        {features.map((f, i) => {
          const d = featurePath(f);
          if (!d) return null;
          return (
            <path
              key={(f.properties && f.properties.unit_id) || `f-${i}`}
              d={d}
              fill="#eef1f3"
              stroke="#cbd2d9"
              strokeWidth="0.5"
            />
          );
        })}

        {/* Selected sector on top: solid accent fill so the locator is
            unmistakable on screen. (Print CSS targets path:last-of-type and
            overrides this to a light-grey wash, so paper stays readable.) */}
        <path
          d={featurePath(selected)}
          fill="rgba(26,127,86,0.85)"
          stroke="#0f5c3d"
          strokeWidth="1.5"
        />

        {/* Points inside the selected sector — small solid dots. */}
        {pts.map((p, i) => {
          if (!p.geometry || p.geometry.type !== 'Point') return null;
          const [x, y] = project(p.geometry.coordinates);
          const isEatery = !!(p.properties && p.properties.is_eatery);
          return (
            <circle
              key={`p-${i}`}
              cx={x.toFixed(2)}
              cy={y.toFixed(2)}
              r="2"
              fill={isEatery ? '#0f5c3d' : '#52606d'}
            />
          );
        })}
      </svg>
      <figcaption className="sector-minimap__cap">
        Where sector {selectedId} sits
      </figcaption>
    </div>
  );
}
