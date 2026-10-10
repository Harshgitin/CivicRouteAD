import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import { 
  Layers, 
  Compass, 
  MapPin, 
  Navigation, 
  ZoomIn, 
  ZoomOut, 
  Maximize, 
  Eye, 
  ExternalLink,
  AlertTriangle
} from 'lucide-react';

const BASEMAP_TILES = {
  dark: {
    name: 'Dark GIS (OSM)',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',
    isDark: true
  },
  streets: {
    name: 'Street Map (OSM)',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',
    isDark: false
  },
  satellite: {
    name: 'Satellite (Esri)',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS',
    isDark: false
  }
};

export default function MapDashboard({ 
  geojsonData, 
  hazards = [], 
  currentTelemetry, 
  selectedHazard, 
  onSelectHazard,
  onSeekToHazard 
}) {
  const mapContainerRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const tileLayerRef = useRef(null);
  const vehicleMarkerRef = useRef(null);
  const trajectoryLayerRef = useRef(null);
  const hazardMarkersLayerRef = useRef(null);
  const fittedTrajectorySignatureRef = useRef(null);

  const [activeBasemap, setActiveBasemap] = useState('dark');
  const [filterSeverity, setFilterSeverity] = useState('ALL');
  const [followVehicle, setFollowVehicle] = useState(true);
  const [tileErrorNotice, setTileErrorNotice] = useState(null);

  const applyBasemap = (map, basemapKey) => {
    if (!map) return;
    if (tileLayerRef.current) {
      map.removeLayer(tileLayerRef.current);
    }
    const cfg = BASEMAP_TILES[basemapKey] || BASEMAP_TILES.dark;

    if (mapContainerRef.current) {
      if (cfg.isDark) {
        mapContainerRef.current.classList.add('leaflet-dark-tiles');
      } else {
        mapContainerRef.current.classList.remove('leaflet-dark-tiles');
      }
    }

    const layer = L.tileLayer(cfg.url, {
      attribution: cfg.attribution,
      maxZoom: 19
    });

    layer.on('tileerror', () => {
      setTileErrorNotice(`Notice: Some tiles failed to load for ${cfg.name}.`);
    });

    layer.addTo(map);
    tileLayerRef.current = layer;
  };

  // Initialize Map
  useEffect(() => {
    if (!mapContainerRef.current) return;
    if (mapInstanceRef.current) return;

    const map = L.map(mapContainerRef.current, {
      center: [45.8914, -123.9615],
      zoom: 16,
      zoomControl: false
    });

    applyBasemap(map, 'dark');

    trajectoryLayerRef.current = L.layerGroup().addTo(map);
    hazardMarkersLayerRef.current = L.layerGroup().addTo(map);

    mapInstanceRef.current = map;

    return () => {
      map.remove();
      mapInstanceRef.current = null;
    };
  }, []);

  // Switch Basemaps
  useEffect(() => {
    if (!mapInstanceRef.current) return;
    applyBasemap(mapInstanceRef.current, activeBasemap);
  }, [activeBasemap]);

  // Update Trajectory and Hazard Markers when GeoJSON changes
  useEffect(() => {
    if (!mapInstanceRef.current || !geojsonData) return;
    const map = mapInstanceRef.current;

    trajectoryLayerRef.current.clearLayers();
    hazardMarkersLayerRef.current.clearLayers();

    const features = geojsonData.features || [];

    // 1. Draw Trajectory Line
    const trajectoryFeature = features.find(
      (f) => f.properties?.feature_class === 'survey_trajectory'
    );

    if (trajectoryFeature && trajectoryFeature.geometry?.coordinates) {
      // Leaflet expects [lat, lon]
      const latlngs = trajectoryFeature.geometry.coordinates.map((c) => [c[1], c[0]]);

      const polyline = L.polyline(latlngs, {
        color: '#06b6d4',
        weight: 5,
        opacity: 0.85,
        smoothFactor: 1
      });

      polyline.addTo(trajectoryLayerRef.current);

      // Fit bounds only when a different trajectory arrives. Live inference adds
      // hazard features repeatedly while the video plays; refitting on every frame
      // would make the map visibly jump and fight the user's pan/zoom.
      if (latlngs.length > 0) {
        const first = latlngs[0];
        const last = latlngs[latlngs.length - 1];
        const signature = `${latlngs.length}:${first[0].toFixed(6)},${first[1].toFixed(6)}:${last[0].toFixed(6)},${last[1].toFixed(6)}`;
        if (signature !== fittedTrajectorySignatureRef.current) {
          map.fitBounds(polyline.getBounds(), { padding: [40, 40] });
          fittedTrajectorySignatureRef.current = signature;
        }
      }
    }

    // 2. Draw Hazard Points with Custom Markers
    const hazardFeatures = features.filter(
      (f) => f.properties?.feature_class === 'road_hazard'
        && f.geometry?.type === 'Point'
        && Array.isArray(f.geometry.coordinates)
        && f.geometry.coordinates.length >= 2
    );

    hazardFeatures.forEach((feat) => {
      const p = feat.properties;
      const [lon, lat] = feat.geometry.coordinates;

      if (filterSeverity !== 'ALL' && p.severity !== filterSeverity) {
        return;
      }

      const isCritical = p.severity === 'Critical';
      const color = p.marker_color || (isCritical ? '#ef4444' : '#f59e0b');

      // Create animated HTML marker icon
      const iconHtml = `
        <div class="relative flex items-center justify-center cursor-pointer ${isCritical ? 'animate-radar' : ''}">
          <div style="background-color: ${color};" class="w-7 h-7 rounded-full border-2 border-white flex items-center justify-center text-white shadow-lg text-xs font-bold">
            !
          </div>
        </div>
      `;

      const customIcon = L.divIcon({
        className: 'custom-hazard-marker',
        html: iconHtml,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
        popupAnchor: [0, -16]
      });

      const marker = L.marker([lat, lon], { icon: customIcon });

      // Rich popup content
      const popupHtml = `
        <div class="p-3 w-64 text-slate-100 font-sans">
          <div class="flex items-center justify-between gap-2 mb-2 pb-2 border-b border-slate-700">
            <span class="font-bold text-xs text-white">${p.hazard_id}</span>
            <span class="text-[10px] font-bold px-2 py-0.5 rounded-full ${
              isCritical ? 'bg-red-500/20 text-red-400 border border-red-500/30' : 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
            }">${p.severity}</span>
          </div>

          ${p.snapshot_url ? `
            <div class="mb-2 rounded-lg overflow-hidden border border-slate-700 aspect-video bg-black flex items-center justify-center">
              <img src="${p.snapshot_url}" alt="${p.label}" class="w-full h-full object-cover" />
            </div>
          ` : ''}

          <h4 class="font-bold text-sm text-cyan-300 mb-1">${p.label}</h4>
          
          <div class="grid grid-cols-2 gap-1.5 text-[11px] font-mono text-slate-300 mb-2.5">
            <div><span class="text-slate-400">Est. forward:</span> ${p.forward_distance_m}m</div>
            <div><span class="text-slate-400">Est. lateral:</span> ${p.lateral_offset_m}m</div>
            <div class="col-span-2 text-slate-400 truncate">${p.lane_location}</div>
            <div class="col-span-2 text-amber-300">${String(p.location_quality || '').includes('unanchored') ? 'GPS coverage unavailable at detection time; position is not anchored.' : 'Approximate camera projection · accuracy not calibrated'}</div>
          </div>

          <div class="bg-slate-800/80 p-2 rounded border border-slate-700/60 text-[10px] text-slate-300 mb-2">
            <strong class="text-amber-400 block mb-0.5">Municipal Dispatch:</strong>
            ${p.suggested_action}
          </div>

          <button 
            id="btn-seek-${p.hazard_id}" 
            class="w-full bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs py-1.5 rounded transition-colors"
          >
            Seek Video to Detection
          </button>
        </div>
      `;

      marker.bindPopup(popupHtml);

      marker.on('popupopen', () => {
        const btn = document.getElementById(`btn-seek-${p.hazard_id}`);
        if (btn) {
          btn.onclick = () => {
            const h = hazards.find((hz) => hz.id === p.hazard_id);
            if (h) onSeekToHazard(h);
          };
        }
      });

      marker.on('click', () => {
        const h = hazards.find((hz) => hz.id === p.hazard_id);
        if (h) onSelectHazard(h);
      });

      marker.addTo(hazardMarkersLayerRef.current);
    });
  }, [geojsonData, filterSeverity, hazards]);

  // Update Moving Vehicle Marker with live telemetry
  useEffect(() => {
    if (!mapInstanceRef.current || !currentTelemetry) return;
    const map = mapInstanceRef.current;
    const { lat, lon, heading_deg } = currentTelemetry;

    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;

    const carHtml = `
      <div class="relative flex items-center justify-center">
        <div 
          style="transform: rotate(${heading_deg}deg);" 
          class="w-8 h-8 rounded-full bg-blue-500 border-2 border-white flex items-center justify-center shadow-2xl text-white transition-transform duration-200"
        >
          <svg class="w-4 h-4 fill-current -rotate-45" viewBox="0 0 24 24">
            <path d="M12 2L4.5 20.29l.71.71L12 18l6.79 3 .71-.71z"/>
          </svg>
        </div>
      </div>
    `;

    const carIcon = L.divIcon({
      className: 'vehicle-marker',
      html: carHtml,
      iconSize: [32, 32],
      iconAnchor: [16, 16]
    });

    if (!vehicleMarkerRef.current) {
      vehicleMarkerRef.current = L.marker([lat, lon], { icon: carIcon }).addTo(map);
    } else {
      vehicleMarkerRef.current.setLatLng([lat, lon]);
      vehicleMarkerRef.current.setIcon(carIcon);
    }

    if (followVehicle) {
      map.panTo([lat, lon], { animate: true, duration: 0.2 });
    }
  }, [currentTelemetry, followVehicle]);

  // Highlight selected hazard from other panels
  useEffect(() => {
    if (!mapInstanceRef.current || !selectedHazard) return;
    const map = mapInstanceRef.current;
    map.setView([selectedHazard.lat, selectedHazard.lon], 18, { animate: true });
  }, [selectedHazard]);

  return (
    <div className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden shadow-2xl flex flex-col h-full relative">
      
      {/* Map Header Toolbar */}
      <div className="bg-slate-900 border-b border-slate-800 p-2.5 px-4 flex flex-wrap items-center justify-between gap-3 z-10">
        <div className="flex items-center gap-2">
          <MapPin className="w-4 h-4 text-cyan-400" />
          <span className="text-xs font-bold text-white uppercase tracking-wider">
            Live GIS Vector Map
          </span>
          <span className="text-[11px] font-mono text-slate-400">
            ({hazards.length} Hazards Logged)
          </span>
        </div>

        {/* Toolbar Controls */}
        <div className="flex items-center gap-2">
          {/* Severity Filter */}
          <select
            value={filterSeverity}
            onChange={(e) => setFilterSeverity(e.target.value)}
            className="bg-slate-800 text-xs text-slate-200 border border-slate-700 rounded px-2 py-1 font-medium focus:outline-none"
          >
            <option value="ALL">All Severities</option>
            <option value="Critical">Critical Only</option>
            <option value="High">High</option>
            <option value="Medium">Medium</option>
            <option value="Low">Low</option>
          </select>

          {/* Basemap Switcher */}
          <div className="flex items-center bg-slate-800 border border-slate-700 rounded p-0.5 text-xs">
            {Object.keys(BASEMAP_TILES).map((k) => (
              <button
                key={k}
                onClick={() => setActiveBasemap(k)}
                className={`px-2 py-0.5 rounded capitalize transition-colors ${
                  activeBasemap === k ? 'bg-blue-600 text-white font-bold' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {k}
              </button>
            ))}
          </div>

          {/* Follow vehicle toggle */}
          <button
            onClick={() => setFollowVehicle(!followVehicle)}
            className={`px-2.5 py-1 text-xs rounded border transition-colors flex items-center gap-1 font-medium ${
              followVehicle
                ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                : 'bg-slate-800 text-slate-400 border-slate-700 hover:text-white'
            }`}
            title="Auto-follow dashcam vehicle on map"
          >
            <Navigation className="w-3 h-3" />
            <span className="hidden sm:inline">Follow Vehicle</span>
          </button>
        </div>
      </div>

      {/* Tile Error Notice Banner */}
      {tileErrorNotice && (
        <div className="bg-amber-950/80 border-b border-amber-600/50 px-3 py-1.5 flex items-center justify-between text-[11px] text-amber-200 z-10">
          <div className="flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
            <span>{tileErrorNotice}</span>
          </div>
          <button
            onClick={() => {
              setActiveBasemap('streets');
              setTileErrorNotice(null);
            }}
            className="text-cyan-400 underline hover:text-cyan-300 font-semibold ml-2 cursor-pointer"
          >
            Switch to Standard OSM
          </button>
        </div>
      )}

      {/* Map DOM Element */}
      <div ref={mapContainerRef} className="flex-1 w-full min-h-[420px] z-0" />
    </div>
  );
}
