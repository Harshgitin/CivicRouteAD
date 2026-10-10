import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  Activity, AlertTriangle, ArrowDownToLine, Building2, CalendarClock,
  CheckCircle2, CircleHelp, ExternalLink, Layers3, LocateFixed, MapPin,
  RefreshCw, Satellite, Search, ShieldCheck, TreePine, Waves, Waypoints,
} from 'lucide-react';
import './AdvancedInfrastructure.css';

const DEFAULT_CENTER = { lat: 20.5937, lon: 78.9629 };
const MAPLIBRE_JS = 'https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js';
const MAPLIBRE_CSS = 'https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css';

const FILTERS = [
  { id: 'all', label: 'All supported issues' },
  { id: 'pothole', label: 'Potholes' },
  { id: 'road_crack', label: 'Road cracks' },
  { id: 'fallen_debris', label: 'Fallen debris / branches' },
  { id: 'waterlogging', label: 'Possible waterlogging' },
  { id: 'other', label: 'Other supported hazards' },
];

const KNOWN_MISSING_SPRITES = [
  'swimming_pool', 'sports_centre', 'office', 'gate', 'lift_gate',
  'bollard', 'atm', 'motorcycle_parking', 'reservoir', 'bicycle_parking',
  'swimming_pool_11', 'sports_centre_11', 'office_11', 'gate_11', 'lift_gate_11',
  'bollard_11', 'atm_11', 'motorcycle_parking_11', 'reservoir_11', 'bicycle_parking_11',
  'swimming_pool_15', 'sports_centre_15', 'office_15', 'gate_15', 'lift_gate_15',
  'bollard_15', 'atm_15', 'motorcycle_parking_15', 'reservoir_15', 'bicycle_parking_15',
];

let mapLibreLoader;
function ensureMapLibre() {
  if (window.maplibregl) return Promise.resolve(window.maplibregl);
  if (mapLibreLoader) return mapLibreLoader;
  mapLibreLoader = new Promise((resolve, reject) => {
    if (!document.querySelector('link[data-civicroute-maplibre]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = MAPLIBRE_CSS;
      link.dataset.civicrouteMaplibre = 'true';
      document.head.appendChild(link);
    }
    const existing = document.querySelector('script[data-civicroute-maplibre]');
    if (existing) {
      existing.addEventListener('load', () => window.maplibregl ? resolve(window.maplibregl) : reject(new Error('MapLibre did not initialize.')), { once: true });
      existing.addEventListener('error', () => reject(new Error('Could not load MapLibre from its CDN.')), { once: true });
      return;
    }
    const script = document.createElement('script');
    script.src = MAPLIBRE_JS;
    script.async = true;
    script.dataset.civicrouteMaplibre = 'true';
    script.onload = () => window.maplibregl ? resolve(window.maplibregl) : reject(new Error('MapLibre did not initialize.'));
    script.onerror = () => reject(new Error('Could not load MapLibre from its CDN. Check your internet connection.'));
    document.head.appendChild(script);
  }).catch((error) => {
    mapLibreLoader = null;
    throw error;
  });
  return mapLibreLoader;
}

function distanceMeters(a, b) {
  const rad = (x) => x * Math.PI / 180;
  const dLat = rad(b.lat - a.lat);
  const dLon = rad(b.lon - a.lon);
  const la1 = rad(a.lat);
  const la2 = rad(b.lat);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLon / 2) ** 2;
  return 6371008.8 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(Math.max(0, 1 - h)));
}

function radiusPolygon(center, radiusM = 1000) {
  if (!center) return { type: 'FeatureCollection', features: [] };
  const coordinates = [];
  const earthRadius = 6371008.8;
  const lat1 = center.lat * Math.PI / 180;
  const lon1 = center.lon * Math.PI / 180;
  for (let i = 0; i <= 72; i += 1) {
    const bearing = (i * 5) * Math.PI / 180;
    const angular = radiusM / earthRadius;
    const lat2 = Math.asin(Math.sin(lat1) * Math.cos(angular) + Math.cos(lat1) * Math.sin(angular) * Math.cos(bearing));
    const lon2 = lon1 + Math.atan2(
      Math.sin(bearing) * Math.sin(angular) * Math.cos(lat1),
      Math.cos(angular) - Math.sin(lat1) * Math.sin(lat2),
    );
    coordinates.push([lon2 * 180 / Math.PI, lat2 * 180 / Math.PI]);
  }
  return {
    type: 'FeatureCollection',
    features: [{ type: 'Feature', properties: { kind: 'radius' }, geometry: { type: 'Polygon', coordinates: [coordinates] } }],
  };
}

function mapStyle(mode) {
  const rasterStyle = (id, tileUrl, attribution) => ({
    version: 8,
    sources: {
      [id]: {
        type: 'raster',
        tiles: [tileUrl],
        tileSize: 256,
        attribution,
        maxzoom: 19,
      },
    },
    layers: [{ id: `${id}-base`, type: 'raster', source: id }],
  });
  if (mode === 'satellite') {
    return rasterStyle(
      'esriWorldImagery',
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      'Imagery &copy; Esri and its imagery providers',
    );
  }
  // Use a raster street basemap for the default mode so a third-party vector
  // style's missing POI sprite images/null numeric feature properties do not
  // flood the console or interfere with CivicRouteAD's own hazard layers.
  if (mode !== '3d') {
    return rasterStyle(
      'esriWorldStreet',
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
      'Map tiles &copy; Esri and its data providers',
    );
  }
  return 'https://tiles.openfreemap.org/styles/liberty';
}

function safeText(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}

function validCoordinate(value, min, max) {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= min && parsed <= max ? parsed : null;
}

function getValidPoint(item) {
  if (!item || typeof item !== 'object') return null;
  const lat = validCoordinate(item.lat ?? item.latitude, -90, 90);
  const lon = validCoordinate(item.lon ?? item.longitude, -180, 180);
  if (lat === null || lon === null) return null;
  return { lat, lon };
}

function hasValidPoint(item) {
  return Boolean(getValidPoint(item));
}

async function runMapillaryScan(center, radiusM, token, filterType) {
  const payload = {
    lat: center.lat,
    lon: center.lon,
    radius_m: radiusM,
    hazard_filter: filterType,
  };
  if (token && token.trim()) {
    payload.access_token = token.trim();
  }
  const response = await fetch('/api/infrastructure/mapillary/scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || body.ok === false) {
    const errorMsg = body.message || body.detail || `Mapillary scan error (${body.status || response.status}).`;
    const err = new Error(errorMsg);
    err.status = body.status;
    err.errors = body.errors || [];
    throw err;
  }
  const candidates = Array.isArray(body.candidates) ? body.candidates.filter(hasValidPoint) : [];
  return {
    status: body.status,
    providerStatus: body.provider_status,
    imageCount: Number(body.images_with_valid_location || 0),
    analyzedCount: Number(body.images_analyzed || 0),
    mapillaryCheckedCount: Number(body.images_checked_by_mapillary || 0),
    mapillaryPotholeCount: Number(body.mapillary_pothole_detections || 0),
    candidates,
    errors: Array.isArray(body.errors) ? body.errors : [],
    detector: body.detector || null,
    notice: body.notice || '',
  };
}

async function fetchOpenStreetMapContext(center, radiusM, category = 'all') {
  const params = new URLSearchParams({
    lat: String(center.lat),
    lon: String(center.lon),
    radius_m: String(radiusM),
    category: String(category || 'all'),
  });
  const response = await fetch(`/api/infrastructure/osm-context?${params.toString()}`);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || `OpenStreetMap context query failed (${response.status}).`);
  }
  if (!body.ok) {
    const err = new Error(body.detail || 'OpenStreetMap context is temporarily unavailable.');
    err.canRetry = Boolean(body.can_retry);
    err.warnings = body.warnings || [];
    throw err;
  }
  return {
    items: Array.isArray(body.items) ? body.items.filter(hasValidPoint) : [],
    warnings: Array.isArray(body.warnings) ? body.warnings : [],
    fromCache: Boolean(body.from_cache),
    provider: body.provider || 'OpenStreetMap',
  };
}

function mapillaryToFeatures(candidates) {
  return {
    type: 'FeatureCollection',
    features: candidates.filter(hasValidPoint).map((item) => {
      const point = getValidPoint(item);
      return {
        type: 'Feature',
        properties: { id: item.id || item.detection_id, kind: item.hazard_type, label: item.label, source: item.source, image_id: item.image_id, captured_at: item.captured_at, status: item.status || 'Unverified' },
        geometry: { type: 'Point', coordinates: [point.lon, point.lat] },
      };
    }),
  };
}

function reportToFeatures(items) {
  return {
    type: 'FeatureCollection',
    features: items.filter(hasValidPoint).map((item) => {
      const point = getValidPoint(item);
      return {
        type: 'Feature',
        properties: { id: item.id, kind: `reported_${item.hazard_type}`, label: item.label, title: item.title, source: item.source, status: item.status, distance_m: Number.isFinite(Number(item.distance_m)) ? Number(item.distance_m) : 0 },
        geometry: { type: 'Point', coordinates: [point.lon, point.lat] },
      };
    }),
  };
}

function contextToFeatures(items) {
  return {
    type: 'FeatureCollection',
    features: items.filter(hasValidPoint).map((item) => {
      const point = getValidPoint(item);
      return {
        type: 'Feature',
        properties: { id: item.id, label: item.label, kind: item.kind, tags: JSON.stringify(item.tags || {}) },
        geometry: { type: 'Point', coordinates: [point.lon, point.lat] },
      };
    }),
  };
}

function downloadBlob(name, content, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function toFeatureCollection(candidates) {
  return {
    type: 'FeatureCollection',
    metadata: {
      system: 'CivicRouteAD Advanced Infrastructure Intelligence',
      generated_at: new Date().toISOString(),
      notice: 'Street-image detections are unverified candidates located at image GPS positions, not survey-grade defect coordinates.',
    },
    features: candidates.filter(hasValidPoint).map((item) => {
      const point = getValidPoint(item);
      return {
      type: 'Feature',
      id: item.id || item.detection_id,
      geometry: { type: 'Point', coordinates: [point.lon, point.lat] },
      properties: {
        incident_id: item.id || item.detection_id,
        label: item.label,
        hazard_type: item.hazard_type,
        source: item.source,
        confidence: item.confidence ?? null,
        captured_at: item.captured_at || null,
        status: item.status || 'Unverified',
        image_page_url: item.image_page_url || '',
        verification: 'unverified_candidate',
      },
    };
    }),
  };
}

function exportCsv(items) {
  const headers = ['id', 'label', 'hazard_type', 'lat', 'lon', 'source', 'confidence', 'captured_at', 'status', 'image_page_url'];
  const cell = (value) => `"${String(value ?? '').replace(/"/g, '""')}"`;
  return [headers.join(','), ...items.map((item) => headers.map((key) => cell(item[key])).join(','))].join('\r\n');
}

export default function AdvancedInfrastructurePage() {
  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const mapLibreRef = useRef(null);
  const leafletMapRef = useRef(null);
  const leafletLayerGroupRef = useRef(null);
  const leafletTilesRef = useRef(null);
  const mapModeRef = useRef('street');
  const mapCenterRef = useRef(DEFAULT_CENTER);
  const centerSelectedRef = useRef(false);
  const radiusRef = useRef(1000);
  const mapCandidatesRef = useRef([]);
  const mapReportsRef = useRef([]);
  const mapContextRef = useRef([]);
  const [center, setCenter] = useState(null);
  const [radiusM, setRadiusM] = useState(1000);
  const [mapMode, setMapMode] = useState('street');
  const [hazardFilter, setHazardFilter] = useState('pothole');
  const [mapillaryToken, setMapillaryToken] = useState('');
  const [serverMapillaryStatus, setServerMapillaryStatus] = useState(null);
  const [diagnostics, setDiagnostics] = useState(null);
  const [showTokenOverride, setShowTokenOverride] = useState(false);
  const [showSetupGuide, setShowSetupGuide] = useState(false);
  const [osmUnavailable, setOsmUnavailable] = useState(false);
  const [osmRetrying, setOsmRetrying] = useState(false);
  const [candidates, setCandidates] = useState([]);
  const [nearbyReports, setNearbyReports] = useState([]);
  const [contextItems, setContextItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState('');
  const [scanMessage, setScanMessage] = useState('Choose your current location to analyze the nearby 1 km area.');
  const [scanWarnings, setScanWarnings] = useState([]);
  const [searchText, setSearchText] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');
  const [staffSession] = useState(() => sessionStorage.getItem('civicroute_staff_session') || '');
  const [updateError, setUpdateError] = useState('');

  mapCenterRef.current = center || DEFAULT_CENTER;
  centerSelectedRef.current = Boolean(center);
  radiusRef.current = radiusM;
  mapModeRef.current = mapMode;
  mapCandidatesRef.current = candidates;
  mapReportsRef.current = nearbyReports;
  mapContextRef.current = contextItems;

  const currentAreaCandidates = useMemo(() => candidates.filter((item) => {
    const point = getValidPoint(item);
    if (!center || !point) return false;
    return distanceMeters(center, point) <= radiusM;
  }), [candidates, center, radiusM]);

  const filteredCandidates = useMemo(() => currentAreaCandidates.filter((item) => {
    const textMatch = `${item.label || ''} ${item.hazard_type || ''} ${item.source || ''}`.toLowerCase().includes(searchText.toLowerCase());
    const hazardMatch = hazardFilter === 'all' || item.hazard_type === hazardFilter;
    const statusMatch = statusFilter === 'All' || (item.status || 'Unverified') === statusFilter;
    return textMatch && hazardMatch && statusMatch;
  }), [currentAreaCandidates, hazardFilter, searchText, statusFilter]);

  const currentAreaContext = useMemo(() => contextItems.filter((item) => {
    const point = getValidPoint(item);
    if (!center || !point) return false;
    return distanceMeters(center, point) <= radiusM;
  }), [contextItems, center, radiusM]);

  const filteredNearbyReports = useMemo(() => nearbyReports.filter((item) => {
    const point = getValidPoint(item);
    if (!center || !point || distanceMeters(center, point) > radiusM) return false;
    const query = `${item.label || ''} ${item.title || ''} ${item.hazard_type || ''}`.toLowerCase();
    if (!query.includes(searchText.toLowerCase())) return false;
    if (hazardFilter !== 'all' && item.hazard_type !== hazardFilter) return false;
    if (statusFilter === 'Verified') return /verified/i.test(String(item.status || ''));
    if (statusFilter === 'Resolved') return /resolved|closed/i.test(String(item.status || ''));
    if (statusFilter === 'Rejected') return /rejected/i.test(String(item.status || ''));
    if (statusFilter === 'Unverified') return !/verified|resolved|rejected/i.test(String(item.status || ''));
    return true;
  }), [nearbyReports, center, radiusM, searchText, hazardFilter, statusFilter]);

  const registerNeutralMissingImage = useCallback((map, imageId) => {
    if (!map || !imageId || map.hasImage(imageId)) return;
    const size = 24;
    const data = new Uint8Array(size * size * 4);
    for (let y = 0; y < size; y += 1) {
      for (let x = 0; x < size; x += 1) {
        const distance = Math.hypot(x - 12, y - 10);
        const inside = distance <= 7.5 || (y >= 10 && y <= 21 && Math.abs(x - 12) <= (21 - y) * 0.55);
        if (!inside) continue;
        const offset = (y * size + x) * 4;
        data[offset] = 100; data[offset + 1] = 116; data[offset + 2] = 139; data[offset + 3] = 235;
      }
    }
    try { map.addImage(imageId, { width: size, height: size, data }, { pixelRatio: 2 }); } catch (_) {}
  }, []);

  const registerAllKnownSprites = useCallback((map) => {
    if (!map) return;
    KNOWN_MISSING_SPRITES.forEach((id) => registerNeutralMissingImage(map, id));
  }, [registerNeutralMissingImage]);

  const patchFillExtrusions = useCallback((map) => {
    if (!map || !map.isStyleLoaded()) return;
    try {
      const style = map.getStyle();
      if (!style || !style.layers) return;
      style.layers.forEach((layer) => {
        if (layer.type === 'fill-extrusion') {
          try {
            map.setPaintProperty(layer.id, 'fill-extrusion-height', [
              'coalesce',
              ['to-number', ['get', 'render_height']],
              ['to-number', ['get', 'height']],
              0
            ]);
            map.setPaintProperty(layer.id, 'fill-extrusion-base', [
              'coalesce',
              ['to-number', ['get', 'render_min_height']],
              ['to-number', ['get', 'min_height']],
              0
            ]);
          } catch (_) {}
        }
      });
    } catch (_) {}
  }, []);

  const refreshLeafletLayers = useCallback(() => {
    const map = leafletMapRef.current;
    const group = leafletLayerGroupRef.current;
    if (!map || !group) return;
    group.clearLayers();
    const activeCenter = mapCenterRef.current;
    if (centerSelectedRef.current) {
      L.circle([activeCenter.lat, activeCenter.lon], {
        radius: radiusRef.current,
        color: '#2563eb', weight: 2, dashArray: '5 5', fillColor: '#3b82f6', fillOpacity: 0.06,
      }).addTo(group);
    }
    mapCandidatesRef.current.forEach((item) => {
      const point = getValidPoint(item);
      if (!activeCenter || !point) return;
      if (distanceMeters(activeCenter, point) > radiusRef.current) return;
      const colors = { pothole: '#dc2626', road_crack: '#ea580c', fallen_debris: '#7c3aed', waterlogging: '#0284c7' };
      L.circleMarker([point.lat, point.lon], {
        radius: 7, color: '#fff', weight: 1.5, fillColor: colors[item.hazard_type] || '#be123c', fillOpacity: 0.95,
      }).bindPopup(`<strong>${safeText(item.label)}</strong><br>${safeText(item.source)}<br>Status: ${safeText(item.status || 'Unverified')}`).addTo(group);
    });
    mapReportsRef.current.forEach((item) => {
      const point = getValidPoint(item);
      if (!activeCenter || !point) return;
      if (distanceMeters(activeCenter, point) > radiusRef.current) return;
      L.circleMarker([point.lat, point.lon], {
        radius: 6, color: '#fff', weight: 1.5, fillColor: '#b45309', fillOpacity: 0.9,
      }).bindPopup(`<strong>${safeText(item.label)}</strong><br>${safeText(item.title)}<br>Resident report · ${safeText(item.status || 'Submitted')}`).addTo(group);
    });
    mapContextRef.current.forEach((item) => {
      const point = getValidPoint(item);
      if (!activeCenter || !point || distanceMeters(activeCenter, point) > radiusRef.current) return;
      L.circleMarker([point.lat, point.lon], { radius: 4, color: '#fff', weight: 1, fillColor: '#64748b', fillOpacity: 0.8 })
        .bindPopup(`<strong>${safeText(item.label)}</strong><br>OpenStreetMap mapped context`).addTo(group);
    });
  }, []);

  const setLeafletBasemap = useCallback((mode) => {
    const map = leafletMapRef.current;
    if (!map) return;
    if (leafletTilesRef.current) map.removeLayer(leafletTilesRef.current);
    const satellite = mode === 'satellite';
    leafletTilesRef.current = L.tileLayer(
      satellite
        ? 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
        : 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      { maxZoom: satellite ? 19 : 19, attribution: satellite ? 'Imagery &copy; Esri and its imagery providers' : '&copy; OpenStreetMap contributors' },
    ).addTo(map);
    if (mode === '3d') {
      setMapError('MapLibre could not load, so the map is in 2D fallback mode. Streets and satellite imagery remain available; 3D buildings require the MapLibre CDN.');
    } else {
      setMapError('MapLibre CDN was unavailable. Using the built-in Leaflet fallback; 3D buildings are unavailable in fallback mode.');
    }
  }, []);

  const refreshLayers = useCallback(() => {
    const map = mapRef.current;
    if (!map || !mapLibreRef.current || !map.isStyleLoaded()) return;
    const radiusSource = map.getSource('civicroute-radius');
    const candidateSource = map.getSource('civicroute-candidates');
    const reportSource = map.getSource('civicroute-reports');
    const contextSource = map.getSource('civicroute-context');
    if (radiusSource) radiusSource.setData(radiusPolygon(mapCenterRef.current, radiusRef.current));
    if (candidateSource) candidateSource.setData(mapillaryToFeatures(mapCandidatesRef.current.filter((item) => {
      const c = mapCenterRef.current;
      const point = getValidPoint(item);
      return c && point && distanceMeters(c, point) <= radiusRef.current;
    })));
    if (reportSource) reportSource.setData(reportToFeatures(mapReportsRef.current.filter((item) => {
      const c = mapCenterRef.current;
      const point = getValidPoint(item);
      return c && point && distanceMeters(c, point) <= radiusRef.current;
    })));
    if (contextSource) contextSource.setData(contextToFeatures(mapContextRef.current.filter((item) => {
      const c = mapCenterRef.current;
      const point = getValidPoint(item);
      return c && point && distanceMeters(c, point) <= radiusRef.current;
    })));
  }, []);

  const installMapLayers = useCallback(() => {
    const map = mapRef.current;
    if (!map || !mapLibreRef.current || !map.isStyleLoaded()) return;
    if (!map.getSource('civicroute-radius')) {
      map.addSource('civicroute-radius', { type: 'geojson', data: radiusPolygon(mapCenterRef.current, radiusRef.current) });
      map.addLayer({ id: 'civicroute-radius-fill', type: 'fill', source: 'civicroute-radius', paint: { 'fill-color': '#3b82f6', 'fill-opacity': 0.07 } });
      map.addLayer({ id: 'civicroute-radius-line', type: 'line', source: 'civicroute-radius', paint: { 'line-color': '#2563eb', 'line-width': 2, 'line-dasharray': [2, 2], 'line-opacity': 0.95 } });
    }
    if (!map.getSource('civicroute-candidates')) {
      map.addSource('civicroute-candidates', { type: 'geojson', data: mapillaryToFeatures(mapCandidatesRef.current) });
      map.addLayer({ id: 'civicroute-candidate-points', type: 'circle', source: 'civicroute-candidates', paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, 4, 15, 8],
        'circle-color': ['match', ['get', 'kind'], 'pothole', '#dc2626', 'road_crack', '#ea580c', 'fallen_debris', '#7c3aed', 'waterlogging', '#0284c7', '#be123c'],
        'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.5, 'circle-opacity': 0.92,
      } });
      map.addLayer({ id: 'civicroute-candidate-labels', type: 'symbol', source: 'civicroute-candidates', minzoom: 15, layout: {
        'text-field': ['get', 'label'], 'text-size': 10, 'text-offset': [0, 1.4], 'text-anchor': 'top', 'text-optional': true,
      }, paint: { 'text-color': '#17324d', 'text-halo-color': '#ffffff', 'text-halo-width': 1.4 } });
    }
    if (!map.getSource('civicroute-reports')) {
      map.addSource('civicroute-reports', { type: 'geojson', data: reportToFeatures(mapReportsRef.current) });
      map.addLayer({ id: 'civicroute-report-points', type: 'circle', source: 'civicroute-reports', paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, 4, 15, 7],
        'circle-color': '#b45309', 'circle-stroke-color': '#fff', 'circle-stroke-width': 1.5, 'circle-opacity': 0.93,
      } });
    }
    if (!map.getSource('civicroute-context')) {
      map.addSource('civicroute-context', { type: 'geojson', data: contextToFeatures(mapContextRef.current) });
      map.addLayer({ id: 'civicroute-context-points', type: 'circle', source: 'civicroute-context', paint: {
        'circle-radius': 4.5, 'circle-color': '#64748b', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1, 'circle-opacity': 0.72,
      } });
    }
    if (mapModeRef.current === '3d' && map.getSource('openmaptiles') && !map.getLayer('civicroute-3d-buildings')) {
      const firstSymbol = map.getStyle().layers?.find((layer) => layer.type === 'symbol')?.id;
      try {
        map.addLayer({
          id: 'civicroute-3d-buildings',
          source: 'openmaptiles',
          'source-layer': 'building',
          type: 'fill-extrusion',
          minzoom: 14,
          filter: ['all', ['!=', ['get', 'hide_3d'], 'true'], ['>', ['to-number', ['get', 'render_height'], 0], 0]],
          paint: {
            'fill-extrusion-color': ['interpolate', ['linear'], ['to-number', ['get', 'render_height'], 0], 0, '#dbe5ef', 20, '#a5b8cc', 80, '#6f879f'],
            'fill-extrusion-height': ['max', ['to-number', ['get', 'render_height'], 0], 0],
            'fill-extrusion-base': ['max', ['to-number', ['get', 'render_min_height'], 0], 0],
            'fill-extrusion-opacity': 0.82,
          },
        }, firstSymbol);
        map.setPitch(55);
        map.setBearing(-16);
      } catch (error) {
        console.warn('3D building layer unavailable in this basemap style:', error);
        setScanWarnings((previous) => previous.some((item) => item.includes('3D building')) ? previous : [...previous, 'The selected vector style does not expose 3D building data at this zoom.']);
      }
    }
    refreshLayers();
  }, [refreshLayers]);

  useEffect(() => {
    let cancelled = false;
    let map = null;
    ensureMapLibre().then((maplibre) => {
      if (cancelled || !mapContainerRef.current) return;
      mapLibreRef.current = maplibre;
      map = new maplibre.Map({
        container: mapContainerRef.current,
        style: mapStyle(mapModeRef.current),
        center: [mapCenterRef.current.lon, mapCenterRef.current.lat],
        zoom: center ? 14.2 : 4.2,
        pitch: mapModeRef.current === '3d' ? 55 : 0,
        attributionControl: true,
      });
      mapRef.current = map;
      // MapLibre's documented event handles missing style sprite images.
      map.on('styleimagemissing', (event) => registerNeutralMissingImage(map, event?.id));
      map.addControl(new maplibre.NavigationControl({ visualizePitch: true }), 'top-right');
      map.addControl(new maplibre.ScaleControl({ maxWidth: 100, unit: 'metric' }), 'bottom-left');
      map.on('load', () => {
        if (cancelled) return;
        registerAllKnownSprites(map);
        patchFillExtrusions(map);
        setMapReady(true);
        installMapLayers();
      });
      map.on('style.load', () => {
        if (cancelled) return;
        registerAllKnownSprites(map);
        patchFillExtrusions(map);
        installMapLayers();
      });
      map.on('click', 'civicroute-candidate-points', (event) => {
        const feature = event.features?.[0];
        if (!feature) return;
        const properties = feature.properties || {};
        const html = `<div class="advanced-map-popup"><strong>${safeText(properties.label || 'Infrastructure candidate')}</strong><p>${safeText(properties.source || 'Street-level imagery')}</p><small>Status: ${safeText(properties.status || 'Unverified')}</small>${properties.image_id ? `<p><a href="https://www.mapillary.com/app/?pKey=${encodeURIComponent(properties.image_id)}" target="_blank" rel="noreferrer">Open source image</a></p>` : ''}</div>`;
        new maplibre.Popup({ closeButton: true, maxWidth: '260px' }).setLngLat(event.lngLat).setHTML(html).addTo(map);
      });
      map.on('mouseenter', 'civicroute-candidate-points', () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', 'civicroute-candidate-points', () => { map.getCanvas().style.cursor = ''; });
      map.on('click', 'civicroute-report-points', (event) => {
        const feature = event.features?.[0];
        if (!feature) return;
        const properties = feature.properties || {};
        const html = `<div class="advanced-map-popup"><strong>${safeText(properties.label || 'Resident report')}</strong><p>${safeText(properties.title || '')}</p><small>Resident-submitted · ${safeText(properties.status || 'Submitted')}</small></div>`;
        new maplibre.Popup({ closeButton: true, maxWidth: '260px' }).setLngLat(event.lngLat).setHTML(html).addTo(map);
      });
      map.on('mouseenter', 'civicroute-report-points', () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', 'civicroute-report-points', () => { map.getCanvas().style.cursor = ''; });
    }).catch((error) => {
      if (cancelled || !mapContainerRef.current) return;
      console.warn('MapLibre unavailable; initializing Leaflet fallback:', error);
      try {
        if (map?.remove) map.remove();
        if (!leafletMapRef.current) {
          const fallback = L.map(mapContainerRef.current, { zoomControl: true, scrollWheelZoom: true })
            .setView(centerSelectedRef.current ? [mapCenterRef.current.lat, mapCenterRef.current.lon] : [DEFAULT_CENTER.lat, DEFAULT_CENTER.lon], centerSelectedRef.current ? 15 : 4);
          leafletMapRef.current = fallback;
          leafletLayerGroupRef.current = L.layerGroup().addTo(fallback);
          setLeafletBasemap(mapModeRef.current);
          setMapReady(true);
          refreshLeafletLayers();
        }
        setScanMessage('MapLibre 3D layer is unavailable. The dashboard is using a 2D map fallback.');
      } catch (fallbackError) {
        setMapError(`Interactive map could not load: ${fallbackError.message || error.message}. The dashboard and exports remain available.`);
      }
    });
    return () => {
      cancelled = true;
      map?.remove();
      if (leafletMapRef.current) {
        leafletMapRef.current.remove();
        leafletMapRef.current = null;
        leafletLayerGroupRef.current = null;
        leafletTilesRef.current = null;
      }
      mapRef.current = null;
      mapLibreRef.current = null;
      setMapReady(false);
    };
    // Only create/destroy map once. Live map data is pushed through refs below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (leafletMapRef.current && !mapLibreRef.current) {
      setLeafletBasemap(mapMode);
      if (mapMode !== '3d' && center) leafletMapRef.current.flyTo([center.lat, center.lon], 15, { duration: 0.5 });
      return;
    }
    const map = mapRef.current;
    if (!map || !mapLibreRef.current) return;
    const switchStyle = mapStyle(mapMode);
    map.setStyle(switchStyle);
    map.once('style.load', () => {
      registerAllKnownSprites(map);
      patchFillExtrusions(map);
      if (mapMode === '3d') {
        map.setPitch(55);
        map.setBearing(-16);
      } else {
        map.setPitch(0);
        map.setBearing(0);
      }
      installMapLayers();
    });
  }, [mapMode, installMapLayers, setLeafletBasemap, registerAllKnownSprites, patchFillExtrusions]);

  useEffect(() => {
    if (center && leafletMapRef.current && !mapLibreRef.current) {
      leafletMapRef.current.flyTo([center.lat, center.lon], 15, { duration: 0.6 });
    }
  }, [center]);

  useEffect(() => {
    if (!mapReady) return;
    refreshLayers();
    refreshLeafletLayers();
  }, [mapReady, center, radiusM, candidates, contextItems, refreshLayers, refreshLeafletLayers]);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/infrastructure/candidates').then((response) => {
      if (!response.ok) throw new Error('Stored candidate API is not available.');
      return response.json();
    }).then((body) => {
      if (!cancelled && Array.isArray(body.items)) setCandidates(body.items);
    }).catch((error) => {
      console.warn('Saved infrastructure candidates were not loaded:', error);
    });

    fetch('/api/infrastructure/mapillary/status')
      .then((response) => response.json())
      .then((data) => {
        if (!cancelled) setServerMapillaryStatus(data);
      })
      .catch((error) => {
        if (!cancelled) setServerMapillaryStatus({ ok: false, status: 'provider_unavailable', message: error.message });
      });

    fetch('/api/infrastructure/diagnostics')
      .then((response) => response.json())
      .then((data) => {
        if (!cancelled) setDiagnostics(data);
      })
      .catch(() => {});

    return () => { cancelled = true; };
  }, []);

  const useCurrentLocation = useCallback(() => {
    setScanMessage('Requesting location permission from your browser…');
    setMapError('');
    if (!navigator.geolocation) {
      setScanMessage('This browser does not provide geolocation. Enter coordinates manually or use a supported browser.');
      return;
    }
    navigator.geolocation.getCurrentPosition((position) => {
      const next = { lat: position.coords.latitude, lon: position.coords.longitude, accuracy: position.coords.accuracy };
      setCenter(next);
      mapCenterRef.current = next;
      setScanMessage(`Location acquired with browser-reported accuracy of ±${Math.round(next.accuracy || 0)} m. The 1 km search circle is measured from this point.`);
      const map = mapRef.current;
      if (map) map.flyTo({ center: [next.lon, next.lat], zoom: 15.2, duration: 900 });
      else leafletMapRef.current?.flyTo([next.lat, next.lon], 15, { duration: 0.9 });
    }, (error) => {
      const messages = {
        1: 'Location permission was denied. Allow location access in your browser settings, or enter coordinates manually.',
        2: 'Your browser could not determine a position. Try again with device location enabled.',
        3: 'Location lookup timed out. Try again.',
      };
      setScanMessage(messages[error.code] || 'Could not obtain the current location.');
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 });
  }, []);

  const setManualCoordinates = (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const lat = Number(form.get('latitude'));
    const lon = Number(form.get('longitude'));
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
      setScanMessage('Enter valid latitude (−90 to 90) and longitude (−180 to 180).');
      return;
    }
    const next = { lat, lon, accuracy: null };
    setCenter(next);
    if (mapRef.current) mapRef.current.flyTo({ center: [lon, lat], zoom: 15.2, duration: 900 });
    else leafletMapRef.current?.flyTo([lat, lon], 15, { duration: 0.9 });
    setScanMessage('Manual center set. Run the 1 km search to refresh results for this location.');
  };

  const retryOsmContext = useCallback(async () => {
    if (!center) return;
    setOsmRetrying(true);
    try {
      const result = await fetchOpenStreetMapContext(center, radiusM, hazardFilter);
      setContextItems(result.items);
      setOsmUnavailable(false);
      setScanMessage(`OpenStreetMap context refreshed successfully (${result.items.length} items loaded).`);
    } catch (err) {
      setScanWarnings((prev) => [...prev, `OpenStreetMap retry failed: ${err.message}`]);
    } finally {
      setOsmRetrying(false);
    }
  }, [center, radiusM, hazardFilter]);

  const runScan = useCallback(async () => {
    if (!center) {
      setScanMessage('Choose your current location or enter a latitude/longitude first.');
      return;
    }
    setLoading(true);
    setScanWarnings([]);
    setScanMessage('Searching public street-imagery coverage and mapped road-condition context within the selected radius…');
    const warnings = [];
    let imageCount = 0;
    let analyzedImageCount = 0;
    let mapillaryCheckedCount = 0;
    let mapillaryPotholeCount = 0;
    let fetchedCandidates = [];
    let residentReports = [];
    let context = [];

    setOsmUnavailable(false);
    const contextPromise = fetchOpenStreetMapContext(center, radiusM, hazardFilter)
      .then((result) => {
        context = result.items;
        setOsmUnavailable(false);
        if (result.warnings && result.warnings.length) {
          warnings.push(...result.warnings.map((warning) => `OpenStreetMap fallback: ${warning}`));
        }
      })
      .catch((error) => {
        setOsmUnavailable(true);
        warnings.push(`OpenStreetMap context temporarily unavailable: ${error.message}`);
      });

    const reportQuery = new URLSearchParams({ lat: String(center.lat), lon: String(center.lon), radius_m: String(radiusM) });
    const reportsPromise = fetch(`/api/infrastructure/nearby-reports?${reportQuery.toString()}`)
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || `Nearby reports query returned ${response.status}`);
        residentReports = Array.isArray(body.items) ? body.items : [];
      })
      .catch((error) => warnings.push(`Existing resident reports unavailable: ${error.message}`));

    const streetPromise = runMapillaryScan(center, radiusM, mapillaryToken.trim(), hazardFilter)
      .then((result) => {
        imageCount = result.imageCount;
        analyzedImageCount = result.analyzedCount;
        mapillaryCheckedCount = result.mapillaryCheckedCount;
        mapillaryPotholeCount = result.mapillaryPotholeCount;
        fetchedCandidates = result.candidates;
        warnings.push(...result.errors.slice(0, 3));
        if (result.notice) setScanMessage(result.notice);
        if (result.errors.length > 3) warnings.push(`${result.errors.length - 3} more street-image detection requests failed.`);
      })
      .catch((error) => {
        warnings.push(`Street-level AI scan: ${error.message}`);
        if (error.status === 'authentication_failed' || error.status === 'not_configured') {
          setServerMapillaryStatus((prev) => ({
            ...prev,
            ok: false,
            status: error.status,
            message: error.message,
          }));
        }
      });

    await Promise.all([contextPromise, streetPromise, reportsPromise]);
    setNearbyReports(residentReports);
    setContextItems(context);

    if (fetchedCandidates.length) {
      try {
        const response = await fetch('/api/infrastructure/candidates/bulk', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ items: fetchedCandidates }),
        });
        if (response.ok) {
          const body = await response.json();
          setCandidates((previous) => {
            const merged = new Map(previous.map((item) => [item.id, item]));
            (body.items || []).forEach((item) => merged.set(item.id, { ...merged.get(item.id), ...item }));
            return [...merged.values()];
          });
        } else {
          warnings.push('Candidates were detected but could not be saved to the local project database. Export is still available for this page session.');
          setCandidates((previous) => [...previous, ...fetchedCandidates.map((item) => ({ ...item, id: item.detection_id, status: 'Unverified' }))]);
        }
      } catch (error) {
        warnings.push(`Candidate storage unavailable: ${error.message}`);
        setCandidates((previous) => [...previous, ...fetchedCandidates.map((item) => ({ ...item, id: item.detection_id, status: 'Unverified' }))]);
      }
    }

    setScanWarnings(warnings);
    const authNote = serverMapillaryStatus?.ok
      ? 'Mapillary API verified. Candidates remain unverified; points mark source camera locations.'
      : (serverMapillaryStatus?.message || 'Mapillary street imagery requires a valid API token in .env');

    setScanMessage(
      `Finished the ${Math.round(radiusM)} m area query: ${imageCount} street-level images with valid positions, ${mapillaryCheckedCount} images checked by Mapillary's native object detector, ${mapillaryPotholeCount} Mapillary pothole detections, ${analyzedImageCount} images analyzed by CivicRouteAD local AI, ${fetchedCandidates.length} candidate detections, and ${context.length} mapped road-condition/context features. ${authNote}`
    );
    setLoading(false);
  }, [center, radiusM, mapillaryToken, hazardFilter, serverMapillaryStatus]);

  const changeStatus = async (candidate, nextStatus) => {
    setUpdateError('');
    if (!staffSession) {
      setUpdateError('Sign in through Staff Workspace before changing persisted verification statuses. Public users can scan and export candidates but cannot approve them.');
      return;
    }
    try {
      const response = await fetch(`/api/infrastructure/candidates/${encodeURIComponent(candidate.id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-Staff-Session': staffSession },
        body: JSON.stringify({ status: nextStatus }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || `Status update failed (${response.status}).`);
      setCandidates((previous) => previous.map((item) => item.id === candidate.id ? { ...item, ...body.item } : item));
    } catch (error) {
      setUpdateError(error.message || 'Could not update candidate status.');
    }
  };

  const categoryCounts = useMemo(() => {
    const counts = { pothole: 0, road_crack: 0, fallen_debris: 0, waterlogging: 0, other: 0 };
    currentAreaCandidates.forEach((item) => { if (Object.hasOwn(counts, item.hazard_type)) counts[item.hazard_type] += 1; });
    return counts;
  }, [currentAreaCandidates]);

  const maxCategory = Math.max(1, ...Object.values(categoryCounts));

  return (
    <main className="advanced-page-shell">
      <section className="advanced-intro">
        <div>
          <div className="advanced-kicker"><Layers3 size={14} /> CIVICROUTEAD / ADVANCED</div>
          <h1>Infrastructure Intelligence</h1>
          <p>Explore nearby street-imagery detections, mapped road-condition context, and candidate faults. Every candidate retains its source and remains unverified until reviewed.</p>
        </div>
        <div className="advanced-live-pill"><span /> GEOSEARCH · 1 KM DEFAULT</div>
      </section>

      <section className="advanced-controls-card">
        <div className="advanced-controls-head">
          <div><strong><LocateFixed size={17} /> Investigate a nearby area</strong><p>Choose your current location or enter coordinates. Location permission is requested only when you click the button.</p></div>
          <button type="button" className="adv-button adv-button-primary" onClick={useCurrentLocation}><LocateFixed size={16} /> Use my current location</button>
        </div>
        <form className="advanced-coordinate-form" onSubmit={setManualCoordinates}>
          <label>Latitude<input name="latitude" type="number" step="any" min="-90" max="90" placeholder="e.g. 18.5204" required /></label>
          <label>Longitude<input name="longitude" type="number" step="any" min="-180" max="180" placeholder="e.g. 73.8567" required /></label>
          <button type="submit" className="adv-button adv-button-secondary">Set coordinates</button>
          <label className="advanced-radius-field">Radius<select value={radiusM} onChange={(event) => setRadiusM(Number(event.target.value))}><option value={500}>500 metres</option><option value={1000}>1 kilometre</option><option value={2000}>2 kilometres</option></select></label>
          <label className="advanced-hazard-field">Detect category<select value={hazardFilter} onChange={(event) => setHazardFilter(event.target.value)}>{FILTERS.map((filter) => <option key={filter.id} value={filter.id}>{filter.label}</option>)}</select></label>
        </form>
        <div className="advanced-provider-status-card">
          <div className="advanced-provider-status-badge">
            {serverMapillaryStatus?.ok ? (
              <span className="status-pill status-ready"><CheckCircle2 size={13} /> Mapillary API Connected & Verified</span>
            ) : serverMapillaryStatus?.status === 'not_configured' ? (
              <span className="status-pill status-unconfigured"><AlertTriangle size={13} /> Mapillary Token Not Configured in .env</span>
            ) : serverMapillaryStatus?.status === 'authentication_failed' ? (
              <span className="status-pill status-error"><AlertTriangle size={13} /> Invalid Mapillary Access Token</span>
            ) : serverMapillaryStatus?.status === 'rate_limited' ? (
              <span className="status-pill status-unconfigured"><AlertTriangle size={13} /> Mapillary Rate Limited</span>
            ) : (
              <span className="status-pill status-unconfigured"><Activity size={13} /> Checking Mapillary configuration…</span>
            )}
            <div className="advanced-provider-help">
              <button type="button" className="adv-link-button" onClick={() => setShowSetupGuide((v) => !v)}>
                {showSetupGuide ? 'Hide token guide' : 'How to configure Mapillary token'}
              </button>
              <span>·</span>
              <button type="button" className="adv-link-button" onClick={() => setShowTokenOverride((v) => !v)}>
                {showTokenOverride ? 'Hide token override' : 'Developer token override (session)'}
              </button>
            </div>
          </div>
          {serverMapillaryStatus && !serverMapillaryStatus.ok && (
            <p style={{ margin: '2px 0 0', fontSize: '9.5px', color: '#64748b' }}>
              {serverMapillaryStatus.message}
            </p>
          )}
          {showSetupGuide && (
            <div style={{ marginTop: '8px', padding: '10px 12px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px', fontSize: '10px', lineHeight: '1.6' }}>
              <strong style={{ display: 'block', color: '#1e293b', marginBottom: '4px' }}>Mapillary Token Setup Instructions:</strong>
              <ol style={{ margin: '0 0 6px 18px', padding: 0 }}>
                <li>Register at <a href="https://www.mapillary.com/developer" target="_blank" rel="noreferrer" style={{ color: '#2563eb' }}>mapillary.com/developer <ExternalLink size={10} /></a>.</li>
                <li>Under &quot;Developer Applications&quot;, click <strong>Register Application</strong> and select Read access.</li>
                <li>Generate a <strong>Client Token</strong>.</li>
                <li>Add it to your backend environment: in <code>Civic_RouteAD/.env</code>, set <code>MAPILLARY_ACCESS_TOKEN=&lt;your_token&gt;</code>.</li>
                <li>Restart the CivicRouteAD backend. The server securely communicates with Mapillary via OAuth headers without exposing the secret to the browser.</li>
              </ol>
            </div>
          )}
          {showTokenOverride && (
            <div className="advanced-token-override-field">
              <label htmlFor="mapillary-override-token" style={{ fontSize: '9.5px', fontWeight: 600, color: '#475569' }}>
                Temporary in-memory token override (for testing only; not saved):
              </label>
              <input
                id="mapillary-override-token"
                type="password"
                autoComplete="off"
                value={mapillaryToken}
                onChange={(event) => setMapillaryToken(event.target.value)}
                placeholder="MLY|... (overrides server .env for this session only)"
                style={{ padding: '6px 10px', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '11px', fontFamily: 'monospace' }}
              />
            </div>
          )}
        </div>
        <div className="advanced-controls-footer">
          <div className="advanced-status-message" role="status"><Activity size={15} /> {scanMessage}</div>
          <button type="button" className="adv-button adv-button-run" disabled={loading || !center} onClick={runScan}>{loading ? <RefreshCw size={16} className="adv-spin" /> : <Search size={16} />}{loading ? 'Analyzing nearby data…' : 'Analyze selected area'}</button>
        </div>
        {scanWarnings.length > 0 && <div className="advanced-warning-list">{scanWarnings.map((warning, index) => <p key={`${index}-${warning}`}><AlertTriangle size={14} /> {warning}</p>)}</div>}
        {osmUnavailable && (
          <div className="advanced-osm-retry-banner">
            <span><AlertTriangle size={14} style={{ verticalAlign: 'middle', marginRight: '6px' }} /> OpenStreetMap context temporarily unavailable (timeout or upstream rate limit).</span>
            <button type="button" className="adv-button adv-button-secondary" style={{ padding: '4px 10px', fontSize: '10px' }} onClick={retryOsmContext} disabled={osmRetrying}>
              {osmRetrying ? <RefreshCw size={12} className="adv-spin" /> : <RefreshCw size={12} />}
              {osmRetrying ? 'Retrying OSM…' : 'Retry OpenStreetMap Context'}
            </button>
          </div>
        )}
        {mapError && <div className="advanced-warning-list"><p><AlertTriangle size={14} /> {mapError}</p></div>}
      </section>

      <section className="advanced-kpi-grid">
        <div className="advanced-kpi-card"><span><Search size={16} /> Candidate detections</span><strong>{currentAreaCandidates.length}</strong><small>Street-imagery detections in this area</small></div>
        <div className="advanced-kpi-card"><span><AlertTriangle size={16} /> Pothole candidates</span><strong>{categoryCounts.pothole}</strong><small>Unverified image-based findings</small></div>
        <div className="advanced-kpi-card"><span><ShieldCheck size={16} /> Resident reports nearby</span><strong>{filteredNearbyReports.length}</strong><small>Existing submissions in the selected radius</small></div>
        <div className="advanced-kpi-card"><span><Waypoints size={16} /> Mapped context</span><strong>{currentAreaContext.length}</strong><small>OSM road-condition/context features</small></div>
      </section>

      <section className="advanced-panel" style={{ marginBottom: '20px', padding: '16px' }}>
        <div className="advanced-panel-heading">
          <div>
            <h2><Layers3 size={17} /> Multi-Source Hazard Detection Capability Matrix</h2>
            <p>Explicit documentation of what each data source and detection engine can truthfully identify.</p>
          </div>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table className="advanced-matrix-table">
            <thead>
              <tr>
                <th>Hazard Category</th>
                <th>Mapillary Native Detections</th>
                <th>CivicRouteAD Local Vision AI</th>
                <th>OpenStreetMap Context</th>
                <th>Satellite / Aerial Imagery</th>
                <th>Resident Incident Reports</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>Potholes</strong></td>
                <td><span className="matrix-supported">✓ Native Class (D40)</span></td>
                <td><span className="matrix-supported">✓ Local Detector</span></td>
                <td><span className="matrix-partial">~ Surface / Smoothness Tags</span></td>
                <td><span className="matrix-unsupported">✗ Resolution Inadequate</span></td>
                <td><span className="matrix-supported">✓ Citizen Verified</span></td>
              </tr>
              <tr>
                <td><strong>Road Cracks & Damaged Pavement</strong></td>
                <td><span className="matrix-unsupported">✗ Not a Native Class</span></td>
                <td><span className="matrix-supported">✓ Local Detector (D00-D20)</span></td>
                <td><span className="matrix-partial">~ Surface / Smoothness Tags</span></td>
                <td><span className="matrix-unsupported">✗ Resolution Inadequate</span></td>
                <td><span className="matrix-supported">✓ Citizen Verified</span></td>
              </tr>
              <tr>
                <td><strong>Fallen Trees & Road Obstructions</strong></td>
                <td><span className="matrix-unsupported">✗ Not a Native Class</span></td>
                <td><span className="matrix-supported">✓ Local Detector (Debris)</span></td>
                <td><span className="matrix-partial">~ Barrier / Construction Tags</span></td>
                <td><span className="matrix-unsupported">✗ Latency / Static Only</span></td>
                <td><span className="matrix-supported">✓ Citizen Verified</span></td>
              </tr>
              <tr>
                <td><strong>Flooding & Waterlogging</strong></td>
                <td><span className="matrix-unsupported">✗ Not a Native Class</span></td>
                <td><span className="matrix-supported">✓ Local Detector (Water)</span></td>
                <td><span className="matrix-partial">~ Waterway / Ford Tags</span></td>
                <td><span className="matrix-partial">~ Macro Flood Inundation</span></td>
                <td><span className="matrix-supported">✓ Citizen Verified</span></td>
              </tr>
              <tr>
                <td><strong>Damaged Signs & Streetlights</strong></td>
                <td><span className="matrix-supported">✓ Native Point Assets</span></td>
                <td><span className="matrix-unsupported">✗ Not Trained for Signs</span></td>
                <td><span className="matrix-partial">~ Traffic Sign / Lamp Tags</span></td>
                <td><span className="matrix-unsupported">✗ Perspective Inadequate</span></td>
                <td><span className="matrix-supported">✓ Citizen Verified</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="advanced-dashboard-grid">
        <div className="advanced-panel advanced-map-panel">
          <div className="advanced-panel-heading"><div><h2><MapPin size={17} /> Nearby hazard map</h2><p>{center ? `${center.lat.toFixed(5)}, ${center.lon.toFixed(5)} · ${Math.round(radiusM)} m radius` : 'No location selected yet'}</p></div><div className="advanced-map-modes" role="group" aria-label="Map style"><button className={mapMode === 'street' ? 'active' : ''} onClick={() => setMapMode('street')} type="button"><Layers3 size={14} /> Streets</button><button className={mapMode === 'satellite' ? 'active' : ''} onClick={() => setMapMode('satellite')} type="button"><Satellite size={14} /> Satellite</button><button className={mapMode === '3d' ? 'active' : ''} onClick={() => setMapMode('3d')} type="button"><Building2 size={14} /> 3D</button></div></div>
          <div className="advanced-map-container" ref={mapContainerRef} aria-label="Interactive map for nearby infrastructure intelligence" />
          <div className="advanced-map-legend"><span><i className="legend-pothole" /> Image pothole candidate</span><span><i className="legend-context" /> OSM context</span><span><i className="legend-radius" /> Search radius</span></div>
          <div className="advanced-attribution-note">Street vector style: OpenFreeMap / OpenStreetMap contributors. Satellite imagery: Esri and source providers. Street imagery/detections: Mapillary when queried. Capture dates and coverage vary.</div>
        </div>

        <div className="advanced-panel advanced-chart-panel">
          <div className="advanced-panel-heading"><div><h2><Activity size={17} /> Fault category distribution</h2><p>Counts come from locally analyzed street-image candidates in the selected radius.</p></div></div>
          <div className="advanced-category-chart">{[
            ['pothole', 'Potholes', '#dc2626'],
            ['road_crack', 'Road cracks', '#ea580c'],
            ['fallen_debris', 'Fallen debris', '#7c3aed'],
            ['waterlogging', 'Waterlogging', '#0284c7'],
            ['other', 'Other hazards', '#be123c'],
          ].map(([id, label, color]) => <div className="advanced-bar-row" key={id}><div><span>{label}</span><strong>{categoryCounts[id]}</strong></div><div className="advanced-bar-track"><span style={{ width: `${(categoryCounts[id] / maxCategory) * 100}%`, background: color }} /></div></div>)}</div>
          <div className="advanced-source-note"><ShieldCheck size={17} /><div><strong>Evidence-first workflow</strong><p>CivicRouteAD's loaded local model analyzes available Mapillary street-image thumbnails. These are dated imagery candidates, not live roadside detections; the point marks the camera location, not the defect's exact ground position.</p></div></div>
          <div className="advanced-source-note"><CircleHelp size={17} /><div><strong>Satellite imagery limitation</strong><p>The satellite layer is for visual context only. This build does not claim automatic satellite pothole detection; individual potholes require high-resolution street-level evidence or your dashcam model.</p></div></div>
        </div>
      </section>

      <section className="advanced-dashboard-grid advanced-secondary-grid">
        <div className="advanced-panel advanced-candidate-panel">
          <div className="advanced-panel-heading"><div><h2><AlertTriangle size={17} /> Infrastructure candidate register</h2><p>Persistent local-AI candidates from Mapillary street images, filtered to the selected search circle.</p></div><div className="advanced-export-actions"><button type="button" disabled={!filteredCandidates.length} onClick={() => downloadBlob('civicroute-infrastructure-candidates.geojson', JSON.stringify(toFeatureCollection(filteredCandidates), null, 2), 'application/geo+json')}><ArrowDownToLine size={14} /> GeoJSON</button><button type="button" disabled={!filteredCandidates.length} onClick={() => downloadBlob('civicroute-infrastructure-candidates.csv', exportCsv(filteredCandidates), 'text/csv;charset=utf-8')}><ArrowDownToLine size={14} /> CSV</button></div></div>
          <div className="advanced-table-controls"><label><Search size={14} /><input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Search faults, labels or sources" /></label><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="Review status"><option>All</option><option>Unverified</option><option>Verified</option><option>Rejected</option><option>Resolved</option></select></div>
          {updateError && <div className="advanced-inline-error"><AlertTriangle size={14} /> {updateError}</div>}
          {filteredCandidates.length === 0 ? <div className="advanced-empty-state"><Search size={25} /><strong>No candidate detections in this area yet</strong><p>Set a location and run an area analysis. Add a Mapillary token to retrieve available street images and run the loaded local road-damage model on their thumbnails. Results depend on coverage and whether a compatible model is loaded.</p></div> : <div className="advanced-candidate-list">{filteredCandidates.map((item) => <article className="advanced-candidate-card" key={item.id || `${item.image_id}-${item.label}`}>
            {item.image_url ? <a href={item.image_page_url} target="_blank" rel="noreferrer" className="advanced-candidate-thumb"><img src={item.image_url} loading="lazy" alt="Mapillary street-level evidence thumbnail" /></a> : <div className="advanced-candidate-thumb advanced-no-thumb"><MapPin size={23} /></div>}
            <div className="advanced-candidate-info"><div className="advanced-candidate-head"><strong>{item.label}</strong><span className={`advanced-status-tag status-${String(item.status || 'Unverified').toLowerCase()}`}>{item.status || 'Unverified'}</span></div><p>{item.hazard_type?.replace(/_/g, ' ')} · {item.source}</p><div className="advanced-candidate-meta"><span>{Number(item.lat).toFixed(5)}, {Number(item.lon).toFixed(5)}</span><span>{item.captured_at ? new Date(item.captured_at).toLocaleDateString() : 'Capture date unavailable'}</span>{item.confidence !== null && item.confidence !== undefined && <span>Score {Number(item.confidence).toFixed(2)} · not calibrated</span>}</div><div className="advanced-candidate-actions"><a href={item.image_page_url} target="_blank" rel="noreferrer">Open source image <ExternalLink size={12} /></a><label>Review status<select value={item.status || 'Unverified'} onChange={(event) => changeStatus(item, event.target.value)} disabled={!staffSession}><option>Unverified</option><option>Verified</option><option>Rejected</option><option>Resolved</option></select></label></div></div>
          </article>)}</div>}
        </div>

        <div className="advanced-panel advanced-context-panel">
          <div className="advanced-panel-heading"><div><h2><TreePine size={17} /> OpenStreetMap context</h2><p>Mapped road tags and hazard context, not AI-confirmed damage.</p></div><span className="advanced-context-count">{currentAreaContext.length} items</span></div>
          {currentAreaContext.length === 0 ? <div className="advanced-empty-state"><Waves size={25} /><strong>No mapped road-condition tags found</strong><p>This does not mean the area has no faults; OpenStreetMap coverage and detail vary considerably.</p></div> : <div className="advanced-context-list">{currentAreaContext.slice(0, 60).map((item) => <div key={item.id} className="advanced-context-item"><span className="advanced-context-icon"><Waypoints size={15} /></span><div><strong>{item.label}</strong><small>{item.source}</small><code>{item.lat.toFixed(5)}, {item.lon.toFixed(5)}</code></div><button type="button" title="Center map on this feature" onClick={() => mapRef.current?.flyTo({ center: [item.lon, item.lat], zoom: 17, duration: 650 })}><MapPin size={14} /></button></div>)}</div>}
          <div className="advanced-context-footnote">Mapped surface tags such as “unpaved” or “poor smoothness” are not proof of a pothole or broken infrastructure. They are included as context for field verification.</div>
        </div>
      </section>

      <section className="advanced-panel advanced-resident-report-panel">
        <div className="advanced-panel-heading"><div><h2><ShieldCheck size={17} /> Nearby resident reports</h2><p>Existing submitted reports near the selected point. These are separate from AI detections.</p></div><span className="advanced-context-count">{filteredNearbyReports.length} reports</span></div>
        {filteredNearbyReports.length === 0 ? <div className="advanced-empty-state"><CircleHelp size={24} /><strong>No stored resident reports in this search area</strong><p>This does not mean there are no infrastructure problems. It only means no existing location-tagged reports matched the selected radius and filters.</p></div> : <div className="advanced-resident-report-list">{filteredNearbyReports.slice(0, 100).map((item) => <article className="advanced-resident-report-item" key={item.id}><div className="advanced-resident-report-icon"><AlertTriangle size={16} /></div><div className="advanced-resident-report-body"><div><strong>{item.label}</strong><span>{item.status || 'Submitted'}</span></div><p>{item.title}</p><small>{Number(item.distance_m).toFixed(0)} m away · {item.id} · {item.created_at ? new Date(item.created_at).toLocaleDateString() : 'Date unavailable'}</small></div><button type="button" title="Center map on this report" onClick={() => { if (mapRef.current) mapRef.current.flyTo({ center: [Number(item.lon), Number(item.lat)], zoom: 17, duration: 650 }); else leafletMapRef.current?.flyTo([Number(item.lat), Number(item.lon)], 17, { duration: 0.65 }); }}><MapPin size={15} /></button></article>)}</div>}
      </section>

      <div className="advanced-footer-notice"><CheckCircle2 size={16} /><p><strong>Operational caution:</strong> automated findings are unverified. Review imagery, date, coordinates and source before creating a municipal work order. Use the existing Analysis Lab for frame-level detection on your own MP4 footage.</p></div>
    </main>
  );
}
