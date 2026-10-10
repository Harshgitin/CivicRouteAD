import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import { LocateFixed, MapPin, MousePointer2 } from 'lucide-react';

export default function LocationPicker({ location, onChange, onUseCurrentLocation, locating }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const accuracyCircleRef = useRef(null);
  const onChangeRef = useRef(onChange);
  const [mapReady, setMapReady] = useState(false);

  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { zoomControl: true, scrollWheelZoom: true, doubleClickZoom: true, zoomSnap: 0.5, wheelDebounceTime: 60 }).setView([22.5, 79], 4);
    L.control.scale({ imperial: false, metric: true, maxWidth: 120 }).addTo(map);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);
    map.on('click', (event) => {
      onChangeRef.current({ lat: Number(event.latlng.lat.toFixed(6)), lon: Number(event.latlng.lng.toFixed(6)), source: 'map_pin' });
    });
    mapRef.current = map;
    setMapReady(true);
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!location || !Number.isFinite(location.lat) || !Number.isFinite(location.lon)) {
      // After a new location request or successful submission, clear every old map overlay.
      if (markerRef.current) {
        map.removeLayer(markerRef.current);
        markerRef.current = null;
      }
      if (accuracyCircleRef.current) {
        map.removeLayer(accuracyCircleRef.current);
        accuracyCircleRef.current = null;
      }
      map.setView([22.5, 79], 4, { animate: true });
      return;
    }
    const point = [location.lat, location.lon];
    if (!markerRef.current) {
      markerRef.current = L.marker(point, { draggable: true }).addTo(map);
      markerRef.current.on('dragend', (event) => {
        const pos = event.target.getLatLng();
        onChangeRef.current({ lat: Number(pos.lat.toFixed(6)), lon: Number(pos.lng.toFixed(6)), source: 'map_pin' });
      });
    } else {
      markerRef.current.setLatLng(point);
    }
    if (accuracyCircleRef.current) {
      map.removeLayer(accuracyCircleRef.current);
      accuracyCircleRef.current = null;
    }
    if (location.source === 'device_gps' && Number.isFinite(location.accuracy) && location.accuracy > 0) {
      accuracyCircleRef.current = L.circle(point, {
        radius: Math.min(location.accuracy, 500),
        color: '#2563eb',
        weight: 1.5,
        fillColor: '#3b82f6',
        fillOpacity: 0.12,
      }).addTo(map);
    }
    map.setView(point, Math.max(map.getZoom(), 15), { animate: true });
  }, [location?.lat, location?.lon]);

  return (
    <section className="location-card">
      <div className="section-heading">
        <div className="section-icon icon-blue"><MapPin size={19} /></div>
        <div><h3>Where is the problem?</h3><p>Pin the exact spot so the response team can find it.</p></div>
      </div>
      <button className="button button-secondary location-button" type="button" onClick={onUseCurrentLocation} disabled={locating}>
        <LocateFixed size={17} /> {locating ? 'Finding your location…' : 'Use my current location'}
      </button>
      <div className="map-instruction"><MousePointer2 size={14} /> Or click the map at the problem location. You can drag the pin to adjust it.</div>
      <div ref={containerRef} className="location-map" aria-label="Select the incident location on the map" />
      <div className={`location-coordinate ${location ? 'location-coordinate-set' : ''}`}>
        <span className="coordinate-dot" />
        {location ? <><strong>{location.source === 'device_gps' ? 'Device location' : 'Pin selected'}</strong><span>{location.lat.toFixed(6)}, {location.lon.toFixed(6)}{location.source === 'device_gps' && Number.isFinite(location.accuracy) ? ` · reported ±${Math.round(location.accuracy)} m` : ''}</span></> : <span>Location not selected yet</span>}
      </div>
      <div className="field-group location-address-field">
        <label htmlFor="landmark">Street, landmark or nearby place <span>Helpful, not required</span></label>
        <input id="landmark" name="landmark" type="text" maxLength={300} placeholder="e.g. outside City Hospital, near the bus stop" />
      </div>
      {!mapReady && <p className="muted-small">Loading location map…</p>}
    </section>
  );
}
