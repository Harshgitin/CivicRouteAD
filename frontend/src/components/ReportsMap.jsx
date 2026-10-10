import React, { useEffect, useRef } from 'react';
import L from 'leaflet';

const TYPE_COLORS = {
  'Damaged road / pothole': '#dc5b4c',
  'Flooding / waterlogging': '#268bd2',
  'Broken footpath': '#bb7b27',
  'Open manhole / drain': '#7c3aed',
  'Fallen tree / road debris': '#15803d',
  'Damaged streetlight / pole': '#b45309',
  'Broken traffic signal': '#c2415b',
  'Unsafe public structure': '#475569',
};

export default function ReportsMap({ reports = [], selectedReport, onSelectReport }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markerLayerRef = useRef(null);
  const onSelectReportRef = useRef(onSelectReport);

  useEffect(() => { onSelectReportRef.current = onSelectReport; }, [onSelectReport]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { zoomControl: true, scrollWheelZoom: true }).setView([22.5, 79], 4);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);
    markerLayerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const layer = markerLayerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();
    const points = [];
    reports.forEach((report) => {
      const lat = Number(report.latitude);
      const lon = Number(report.longitude);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
      const selected = selectedReport?.id === report.id;
      const color = TYPE_COLORS[report.issue_type] || '#2563eb';
      const icon = L.divIcon({
        className: 'report-map-marker',
        html: `<div style="width:${selected ? 28 : 22}px;height:${selected ? 28 : 22}px;background:${color};border:${selected ? 4 : 3}px solid white;border-radius:50%;box-shadow:0 2px 10px rgba(17,24,39,.28);display:flex;align-items:center;justify-content:center;color:white;font-size:10px;font-weight:800">${selected ? '●' : '!'}</div>`,
        iconSize: [selected ? 28 : 22, selected ? 28 : 22],
        iconAnchor: [selected ? 14 : 11, selected ? 14 : 11],
      });
      const marker = L.marker([lat, lon], { icon }).bindPopup(`<div class="map-popup-content"><strong>${String(report.title || 'Infrastructure report').replace(/</g, '&lt;')}</strong><br/><span>${String(report.id || '').replace(/</g, '&lt;')}</span><br/><small>${String(report.status || 'New').replace(/</g, '&lt;')}</small></div>`);
      marker.on('click', () => onSelectReportRef.current?.(report.id));
      marker.addTo(layer);
      points.push([lat, lon]);
    });

    const analysis = selectedReport?.analysis;
    (analysis?.hazards || []).forEach((hazard) => {
      const lat = Number(hazard.lat ?? hazard.latitude);
      const lon = Number(hazard.lon ?? hazard.longitude);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
      const hazardIcon = L.divIcon({
        className: 'report-map-marker',
        html: '<div style="width:13px;height:13px;background:#f59e0b;border:2px solid #fff;border-radius:50%;box-shadow:0 1px 7px rgba(0,0,0,.3)"></div>',
        iconSize: [13, 13], iconAnchor: [6, 6],
      });
      L.marker([lat, lon], { icon: hazardIcon }).bindPopup(`<strong>${String(hazard.type || 'Detected hazard').replace(/</g, '&lt;')}</strong><br/>Preliminary detection · ${hazard.confidence != null ? `${Math.round(hazard.confidence * 100)}% confidence` : 'review required'}`).addTo(layer);
      points.push([lat, lon]);
    });

    const selected = selectedReport && [Number(selectedReport.latitude), Number(selectedReport.longitude)];
    if (selected && selected.every(Number.isFinite)) map.setView(selected, Math.max(map.getZoom(), 14));
    else if (points.length === 1) map.setView(points[0], 13);
    else if (points.length > 1 && !selectedReport) map.fitBounds(points, { padding: [28, 28], maxZoom: 13 });
  }, [reports, selectedReport]);

  return <div ref={containerRef} className="staff-map" aria-label="Map showing reported infrastructure problems" />;
}
