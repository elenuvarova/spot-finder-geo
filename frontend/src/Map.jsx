import { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

// Free, no-API-key vector basemap.
const STYLE_URL = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';

// Antwerp center.
const CENTER = [4.4, 51.21];
const ZOOM = 12;

const SOURCE_ID = 'spots';
const FILL_LAYER_ID = 'spots-fill';
const LINE_LAYER_ID = 'spots-line';
const SELECTED_LAYER_ID = 'spots-selected';

// Grey shown when a hex has no opportunity value (n_food < 3 -> null).
const NO_DATA_COLOR = '#cfd3d8';

/**
 * Build the MapLibre expression that produces the 0..1 value driving the fill.
 *
 * When the vegan lens is on, the effective value is opp_<type> * (1 - vegan_coverage),
 * which discounts zones that already have documented vegan offerings.
 */
function valueExpression(type, vegan) {
  const opp = ['get', `opp_${type}`];
  if (!vegan) return opp;
  return ['*', opp, ['-', 1, ['coalesce', ['get', 'vegan_coverage'], 0]]];
}

/**
 * Fill-color paint expression: red (low) -> green (high) across 0..1, and an
 * explicit grey when opp_<type> is null (no data / below the noise threshold).
 */
function fillColorExpression(type, vegan) {
  const value = valueExpression(type, vegan);
  return [
    'case',
    // opp_<type> is null when n_food < 3 -> render as no-data grey.
    ['==', ['get', `opp_${type}`], null],
    NO_DATA_COLOR,
    [
      'interpolate',
      ['linear'],
      value,
      0.0, '#d73027', // red — low opportunity
      0.25, '#fc8d59',
      0.5, '#fee08b', // amber — middling
      0.75, '#91cf60',
      1.0, '#1a9850', // green — high opportunity
    ],
  ];
}

/**
 * Fill-opacity: hide null hexes a bit, keep data hexes semi-transparent (~0.6).
 */
function fillOpacityExpression(type) {
  return [
    'case',
    ['==', ['get', `opp_${type}`], null],
    0.18,
    0.6,
  ];
}

export default function Map({ data, type, vegan, selectedH3, onSelect }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const loadedRef = useRef(false);
  // Keep the latest onSelect in a ref so the click handler (bound once) stays fresh.
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // Initialize the map once.
  useEffect(() => {
    if (mapRef.current || !containerRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE_URL,
      center: CENTER,
      zoom: ZOOM,
      attributionControl: true,
    });
    mapRef.current = map;

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');

    map.on('load', () => {
      loadedRef.current = true;

      map.addSource(SOURCE_ID, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
        promoteId: 'h3',
      });

      map.addLayer({
        id: FILL_LAYER_ID,
        type: 'fill',
        source: SOURCE_ID,
        paint: {
          'fill-color': fillColorExpression(type, vegan),
          'fill-opacity': fillOpacityExpression(type),
        },
      });

      map.addLayer({
        id: LINE_LAYER_ID,
        type: 'line',
        source: SOURCE_ID,
        paint: {
          'line-color': '#ffffff',
          'line-width': 0.5,
          'line-opacity': 0.4,
        },
      });

      // Highlight outline for the selected hex.
      map.addLayer({
        id: SELECTED_LAYER_ID,
        type: 'line',
        source: SOURCE_ID,
        paint: {
          'line-color': '#1f2933',
          'line-width': 2.5,
        },
        filter: ['==', ['get', 'h3'], '__none__'],
      });

      map.on('click', FILL_LAYER_ID, (e) => {
        const feature = e.features && e.features[0];
        if (feature && onSelectRef.current) {
          onSelectRef.current(feature.properties);
        }
      });

      map.on('mouseenter', FILL_LAYER_ID, () => {
        map.getCanvas().style.cursor = 'pointer';
      });
      map.on('mouseleave', FILL_LAYER_ID, () => {
        map.getCanvas().style.cursor = '';
      });
    });

    return () => {
      map.remove();
      mapRef.current = null;
      loadedRef.current = false;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Push data into the source when it changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !data) return;

    const apply = () => {
      const src = map.getSource(SOURCE_ID);
      if (src) src.setData(data);
    };

    if (loadedRef.current) apply();
    else map.once('load', apply);
  }, [data]);

  // Re-paint when the selected type or vegan lens changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loadedRef.current) return;
    if (!map.getLayer(FILL_LAYER_ID)) return;

    map.setPaintProperty(FILL_LAYER_ID, 'fill-color', fillColorExpression(type, vegan));
    map.setPaintProperty(FILL_LAYER_ID, 'fill-opacity', fillOpacityExpression(type));
  }, [type, vegan]);

  // Update the selected-hex highlight.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loadedRef.current) return;
    if (!map.getLayer(SELECTED_LAYER_ID)) return;

    map.setFilter(SELECTED_LAYER_ID, ['==', ['get', 'h3'], selectedH3 || '__none__']);
  }, [selectedH3]);

  return <div ref={containerRef} className="map-container" aria-label="Map of Antwerp" />;
}
