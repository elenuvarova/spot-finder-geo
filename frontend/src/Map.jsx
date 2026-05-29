import { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { buildScoreExpression } from './blend.js';

// Free, no-API-key vector basemap.
const STYLE_URL = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';

// Antwerp center.
const CENTER = [4.4, 51.21];
const ZOOM = 12;

const SOURCE_ID = 'spots';
const FILL_LAYER_ID = 'spots-fill';
const LINE_LAYER_ID = 'spots-line';
const SELECTED_LAYER_ID = 'spots-selected';

// Establishments of the selected sector, drawn on top of the choropleth.
const SEL_POINTS_SOURCE_ID = 'sel-points';
const SEL_POINTS_LAYER_ID = 'sel-points-circles';

const EMPTY_FC = { type: 'FeatureCollection', features: [] };

// Grey shown when a hex has no opportunity value (n_food < 3 -> null).
const NO_DATA_COLOR = '#cfd3d8';

/**
 * Fill-color paint expression: red (low) -> green (high) across 0..1, and an
 * explicit grey when opp_<type> is null (no data / below the noise threshold).
 *
 * The score VALUE comes from blend.js' buildScoreExpression so the choropleth
 * always agrees with scoreFeature (the JS scorer used by TopZones/Compare).
 */
function fillColorExpression(type, lens, blend) {
  const value = buildScoreExpression(type, lens, blend);
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

// Normalise an incoming selectedPoints prop (FeatureCollection or array of
// features) to a FeatureCollection the map source can consume.
function toFeatureCollection(selectedPoints) {
  if (!selectedPoints) return EMPTY_FC;
  if (Array.isArray(selectedPoints)) {
    return { type: 'FeatureCollection', features: selectedPoints };
  }
  if (selectedPoints.type === 'FeatureCollection' && Array.isArray(selectedPoints.features)) {
    return selectedPoints;
  }
  return EMPTY_FC;
}

export default function Map({
  data,
  type,
  lens,
  blend,
  selectedId,
  selectedPoints,
  view,
  focus,
  onSelect,
}) {
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
        promoteId: 'unit_id',
      });

      map.addLayer({
        id: FILL_LAYER_ID,
        type: 'fill',
        source: SOURCE_ID,
        paint: {
          'fill-color': fillColorExpression(type, lens, blend),
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
        filter: ['==', ['get', 'unit_id'], '__none__'],
      });

      // Establishments of the selected sector — added empty, filled on demand.
      map.addSource(SEL_POINTS_SOURCE_ID, {
        type: 'geojson',
        data: EMPTY_FC,
      });

      map.addLayer({
        id: SEL_POINTS_LAYER_ID,
        type: 'circle',
        source: SEL_POINTS_SOURCE_ID,
        paint: {
          'circle-radius': 3.5,
          'circle-color': [
            'case',
            ['==', ['get', 'is_eatery'], true],
            '#1a7f56',
            '#7b8794',
          ],
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 1,
          'circle-opacity': 0.95,
        },
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

  // Re-paint when the selected type, lens, or blend changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loadedRef.current) return;
    if (!map.getLayer(FILL_LAYER_ID)) return;

    map.setPaintProperty(FILL_LAYER_ID, 'fill-color', fillColorExpression(type, lens, blend));
    map.setPaintProperty(FILL_LAYER_ID, 'fill-opacity', fillOpacityExpression(type));
  }, [type, lens, blend]);

  // Update the selected-hex highlight.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loadedRef.current) return;
    if (!map.getLayer(SELECTED_LAYER_ID)) return;

    map.setFilter(SELECTED_LAYER_ID, ['==', ['get', 'unit_id'], selectedId || '__none__']);
  }, [selectedId]);

  // Update the establishments overlay when the selected sector's points change.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      const src = map.getSource(SEL_POINTS_SOURCE_ID);
      if (src) src.setData(toFeatureCollection(selectedPoints));
    };

    if (loadedRef.current && map.getSource(SEL_POINTS_SOURCE_ID)) apply();
    else map.once('load', apply);
  }, [selectedPoints]);

  // Recenter the map when the selected city (view) changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !view || !view.center) return;
    map.flyTo({ center: view.center, zoom: view.zoom ?? ZOOM, duration: 700 });
  }, [view]);

  // Fly to a focused location (e.g. a TopZones / Compare row click).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !focus || !focus.center) return;
    const center = focus.center;
    if (!Array.isArray(center) || center.length < 2) return;
    if (!Number.isFinite(Number(center[0])) || !Number.isFinite(Number(center[1]))) return;
    map.flyTo({ center, zoom: focus.zoom ?? Math.max(map.getZoom(), 13), duration: 700 });
  }, [focus]);

  return <div ref={containerRef} className="map-container" aria-label="Map of Antwerp" />;
}
