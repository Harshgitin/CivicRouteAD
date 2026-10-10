import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import { MapPin, Save } from 'lucide-react';

export default function ReportLocationEditor({ initialLocation, onSave, saving = false }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const onPointRef = useRef(null);
  const [point, setPoint] = useState(() => ({ lat: Number(initialLocation?.lat), lon: Number(initialLocation?.lon) }));

  useEffect(() => { onPointRef.current = setPoint; }, []);
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const valid = Number.isFinite(point.lat) && Number.isFinite(point.lon) && Math.abs(point.lat) <= 90 && Math.abs(point.lon) <= 180;
    const map = L.map(containerRef.current, { scrollWheelZoom: true, doubleClickZoom: true, zoomControl: true }).setView(valid ? [point.lat, point.lon] : [22.5, 79], valid ? 16 : 4);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
    L.control.scale({ imperial: false, metric: true, maxWidth: 120 }).addTo(map);
    markerRef.current = L.marker(valid ? [point.lat, point.lon] : [22.5, 79], { draggable: true }).addTo(map);
    markerRef.current.on('dragend', (event) => {
      const pos = event.target.getLatLng();
      onPointRef.current?.({ lat: Number(pos.lat.toFixed(6)), lon: Number(pos.lng.toFixed(6)) });
    });
    map.on('click', (event) => onPointRef.current?.({ lat: Number(event.latlng.lat.toFixed(6)), lon: Number(event.latlng.lng.toFixed(6)) }));
    mapRef.current = map;
    const timer = window.setTimeout(() => map.invalidateSize(), 80);
    return () => { window.clearTimeout(timer); map.remove(); mapRef.current = null; markerRef.current = null; };
  }, []);

  useEffect(() => {
    if (!markerRef.current || !mapRef.current || !Number.isFinite(point.lat) || !Number.isFinite(point.lon)) return;
    markerRef.current.setLatLng([point.lat, point.lon]);
  }, [point.lat, point.lon]);

  const save = () => {
    if (Number.isFinite(point.lat) && Number.isFinite(point.lon) && Math.abs(point.lat) <= 90 && Math.abs(point.lon) <= 180) onSave(point);
  };

  return <section className="report-location-editor">
    <div className="report-location-editor-heading"><div><strong><MapPin size={16} /> Correct incident pin</strong><span>Click the map or drag the marker to the actual problem site.</span></div></div>
    <div ref={containerRef} className="report-location-editor-map" aria-label="Adjust reported incident coordinates" />
    <div className="report-location-editor-footer"><code>{point.lat.toFixed(6)}, {point.lon.toFixed(6)}</code><button className="button button-primary button-small" type="button" onClick={save} disabled={saving}><Save size={15} /> {saving ? 'Saving…' : 'Save corrected location'}</button></div>
  </section>;
}
