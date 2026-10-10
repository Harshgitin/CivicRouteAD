/**
 * CivicRouteAD - API Client
 * Facilitates backend communication for road hazard AI pipeline & GIS exports.
 */

const API_BASE = '/api';

export async function fetchHealth() {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error('Health check failed');
  return res.json();
}

export async function fetchScenarios() {
  const res = await fetch(`${API_BASE}/scenarios`);
  if (!res.ok) throw new Error('Failed to fetch benchmark scenarios');
  return res.json();
}

export async function processScenario(scenarioId) {
  const res = await fetch(`${API_BASE}/process/scenario/${scenarioId}`, {
    method: 'POST'
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Scenario processing failed');
  }
  return res.json();
}

// Fast Analysis Lab startup: return a playable demo and let the complete GIS pass
// run in the background. The synchronous endpoint remains available for tools/tests
// that explicitly need a fully processed scenario in one response.
export async function previewScenario(scenarioId) {
  const res = await fetch(`${API_BASE}/scenario/preview/${encodeURIComponent(scenarioId)}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Scenario preview failed');
  }
  return res.json();
}

export async function processUpload(videoFile, gpsFile = null, timeOffsetSec = 0.0) {
  const formData = new FormData();
  formData.append('video', videoFile);
  if (gpsFile) formData.append('gps', gpsFile);
  formData.append('time_offset_sec', String(timeOffsetSec || 0.0));

  const res = await fetch(`${API_BASE}/process/upload`, {
    method: 'POST',
    body: formData
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Upload processing failed');
  }
  return res.json();
}


export async function detectVideoFrame(frameBlob, timestampSec = 0, runId = null) {
  const formData = new FormData();
  formData.append('frame', frameBlob, 'dashcam-frame.jpg');
  formData.append('timestamp_sec', String(timestampSec || 0));
  if (runId) formData.append('run_id', runId);
  const res = await fetch(`${API_BASE}/detect/frame`, { method: 'POST', body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Live frame detection failed');
  }
  return res.json();
}

export async function fetchRunStatus(runId) {
  const res = await fetch(`${API_BASE}/process/status/${runId}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to check GIS processing status');
  }
  return res.json();
}

export async function fetchGeoJSON(runId) {
  const res = await fetch(`${API_BASE}/geojson/${runId}`);
  if (!res.ok) throw new Error('Failed to load GeoJSON');
  return res.json();
}

export async function fetchTelemetry(runId) {
  const res = await fetch(`${API_BASE}/telemetry/${runId}`);
  if (!res.ok) throw new Error('Failed to load telemetry');
  return res.json();
}

export async function fetchReport(runId) {
  const res = await fetch(`${API_BASE}/export/report/${runId}`);
  if (!res.ok) throw new Error('Failed to load Municipal Report');
  return res.json();
}

export function downloadFile(url, filename) {
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}
