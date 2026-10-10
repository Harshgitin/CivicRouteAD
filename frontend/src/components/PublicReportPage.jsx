import React, { useRef, useState } from 'react';
import {
  ArrowRight, CheckCircle2, CircleHelp, FileVideo2, LocateFixed, MapPin,
  ShieldCheck, Upload, Video, Waves, Construction, Footprints, Lightbulb,
  TreePine, CircleAlert, Camera, Gauge, LoaderCircle, FileCheck2
} from 'lucide-react';
import LocationPicker from './LocationPicker';

const ISSUE_TYPES = [
  'Damaged road / pothole', 'Flooding / waterlogging', 'Broken footpath',
  'Open manhole / drain', 'Fallen tree / road debris', 'Damaged streetlight / pole',
  'Broken traffic signal', 'Unsafe public structure', 'Other infrastructure problem'
];

export default function PublicReportPage() {
  const [location, setLocation] = useState(null);
  const [locationConfirmed, setLocationConfirmed] = useState(false);
  const [locating, setLocating] = useState(false);
  const [video, setVideo] = useState(null);
  const [gps, setGps] = useState(null);
  const [error, setError] = useState('');
  const [locationNotice, setLocationNotice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(null);
  const [advanced, setAdvanced] = useState(false);
  const [issueType, setIssueType] = useState(ISSUE_TYPES[0]);
  const [cameraSource, setCameraSource] = useState('Phone / dashcam');
  const formRef = useRef(null);

  const useCurrentLocation = () => {
    setError('');
    setLocationNotice('');
    if (!navigator.geolocation) {
      setError('This browser does not provide device location. Click the map to select the infrastructure problem location.');
      return;
    }
    if (!window.isSecureContext && !['localhost', '127.0.0.1'].includes(window.location.hostname)) {
      setError('Browser location requires HTTPS. Open the secure website or select the problem location directly on the map.');
      return;
    }

    // Never leave the old marker displayed as if it were a new fix.
    const previousDeviceLocation = location?.source === 'device_gps' ? { ...location } : null;
    setLocation(null);
    setLocationConfirmed(false);
    setLocating(true);

    let watchId = null;
    let finished = false;
    let candidateTimer = null;
    let hardTimeout = null;
    const readings = [];
    let bestReading = null;

    const distanceMeters = (a, b) => {
      const rad = (v) => (v * Math.PI) / 180;
      const dLat = rad(b.lat - a.lat);
      const dLon = rad(b.lon - a.lon);
      const x = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
      return 6371000 * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(Math.max(0, 1 - x)));
    };

    const cleanup = () => {
      if (watchId !== null) navigator.geolocation.clearWatch(watchId);
      if (candidateTimer !== null) window.clearTimeout(candidateTimer);
      if (hardTimeout !== null) window.clearTimeout(hardTimeout);
    };

    const rejectRepeatedFix = (reading) => previousDeviceLocation &&
      distanceMeters(previousDeviceLocation, reading) < 35;

    const finish = (message, reading = null) => {
      if (finished) return;
      finished = true;
      cleanup();
      setLocating(false);
      if (!reading) {
        setError(message);
        setLocationNotice('');
        return;
      }
      // If a second request returns essentially the exact previous device fix, do not
      // silently reuse it. This is a useful warning for Windows/browser default-location bugs.
      if (rejectRepeatedFix(reading)) {
        setError('Your browser returned the same coordinates as the previous device-location request. It may be using a stale or default location. This fix was not reused. Check Windows Location services, or click the map and pin the actual problem spot.');
        setLocationNotice('');
        return;
      }
      setLocation({
        lat: reading.lat,
        lon: reading.lon,
        source: 'device_gps',
        accuracy: reading.accuracy,
        timestamp: reading.timestamp,
      });
      setLocationNotice(`${message} Reported accuracy: about ±${Math.round(reading.accuracy)} m. Verify the pin is at the infrastructure problem before submitting.`);
      setError('');
    };

    const considerPosition = (position) => {
      const { latitude, longitude, accuracy } = position.coords || {};
      const timestamp = Number(position.timestamp);
      const ageMs = Date.now() - timestamp;
      if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || !Number.isFinite(accuracy) ||
          latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180 ||
          accuracy <= 0 || accuracy > 150 || !Number.isFinite(timestamp) || ageMs < -5000 || ageMs > 15000) return;

      const reading = { lat: latitude, lon: longitude, accuracy, timestamp };
      if (!readings.some((item) => Math.abs(item.timestamp - reading.timestamp) < 200)) readings.push(reading);
      while (readings.length > 4) readings.shift();
      readings.sort((a, b) => a.accuracy - b.accuracy);
      bestReading = readings[0];
      const best = bestReading;

      // A single fresh fix is accepted after a short settling period so desktop
      // browsers that only emit one usable reading do not time out unnecessarily.
      if (candidateTimer === null) {
        candidateTimer = window.setTimeout(() => {
          if (bestReading && Math.abs(Date.now() - bestReading.timestamp) <= 20000) {
            finish('A fresh device-location reading was received.', bestReading);
          }
        }, 6500);
      }

      if (readings.length >= 2) {
        const newest = [...readings].sort((a, b) => b.timestamp - a.timestamp).slice(0, 2);
        if (distanceMeters(newest[0], newest[1]) <= Math.max(100, newest[0].accuracy + newest[1].accuracy)) {
          finish('Two consistent device-location readings were received.', best);
        }
      }
    };

    hardTimeout = window.setTimeout(() => {
      const best = bestReading || readings.sort((a, b) => a.accuracy - b.accuracy)[0];
      if (best && Math.abs(Date.now() - best.timestamp) <= 20000) {
        finish('A fresh device-location reading was received.', best);
      } else {
        finish('No fresh, reasonably accurate device location was returned. Allow location access in your browser and Windows settings, or click the map to pin the problem location.');
      }
    }, 18000);

    try {
      watchId = navigator.geolocation.watchPosition(
        considerPosition,
        (err) => {
          const reason = err.code === 1
            ? 'Location permission was denied.'
            : err.code === 2
              ? 'Windows or the browser could not determine the device location.'
              : 'The device-location request timed out.';
          const best = bestReading || readings.sort((a, b) => a.accuracy - b.accuracy)[0];
          if (best && Math.abs(Date.now() - best.timestamp) <= 20000) {
            finish('A fresh device-location reading was received despite a later location error.', best);
          } else {
            finish(`${reason} Enable Location services and browser permission, or click the map to select the problem location.`);
          }
        },
        { enableHighAccuracy: true, timeout: 17000, maximumAge: 0 }
      );
    } catch {
      finish('The browser could not start device-location services. Check browser permission, or click the map to select the problem location.');
    }
  };
  const handleVideo = (file) => {
    setError('');
    if (!file) return;
    const ext = file.name.split('.').pop()?.toLowerCase();
    if (!['mp4', 'webm', 'mov', 'avi', 'mkv'].includes(ext)) {
      setVideo(null); setError('Please choose a video in MP4, WebM, MOV, AVI or MKV format.'); return;
    }
    if (file.size > 500 * 1024 * 1024) {
      setVideo(null); setError('The video must be 500 MB or smaller.'); return;
    }
    setVideo(file);
  };

  const handleGps = (file) => {
    setError('');
    if (!file) return;
    const ext = file.name.split('.').pop()?.toLowerCase();
    if (!['gpx', 'csv'].includes(ext)) { setGps(null); setError('GPS track must be a GPX or CSV file.'); return; }
    if (file.size > 25 * 1024 * 1024) { setGps(null); setError('GPS track must be 25 MB or smaller.'); return; }
    setGps(file);
  };

  const submitReport = async (event) => {
    event.preventDefault();
    setError('');
    if (!location) { setError('Please use your current location or click the map to pin where the issue is.'); return; }
    if (!locationConfirmed) { setError('Please confirm that the map pin marks the actual infrastructure problem before submitting.'); return; }
    if (location.source === 'device_gps' && Number.isFinite(location.accuracy) && location.accuracy > 100) { setError('Device location accuracy is too broad. Please pin the exact problem spot on the map.'); return; }
    if (!video) { setError('Please attach a short video showing the infrastructure problem.'); return; }
    const form = new FormData(event.currentTarget);
    form.set('video', video);
    form.set('latitude', String(location.lat));
    form.set('longitude', String(location.lon));
    form.set('location_source', location.source || 'map_pin');
    form.set('issue_type', issueType);
    form.set('camera_source', cameraSource);
    form.set('reporter_consent', 'yes');
    if (gps) form.set('gps', gps); else form.delete('gps');
    setSubmitting(true);
    try {
      const response = await fetch('/api/reports', { method: 'POST', body: form });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || 'The report could not be sent. Please try again.');
      setSuccess(result);
      setVideo(null); setGps(null); setLocation(null); setLocationConfirmed(false); setLocationNotice(''); setIssueType(ISSUE_TYPES[0]); setCameraSource('Phone / dashcam'); setAdvanced(false);
      formRef.current?.reset();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      setError(err.message || 'Network error while submitting the report.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="public-page page-shell">
      <section className="hero-grid">
        <div className="hero-copy">
          <div className="eyebrow"><span className="eyebrow-dot" /> COMMUNITY INFRASTRUCTURE REPORTING</div>
          <h1>See a problem.<br /><span>Help fix the route.</span></h1>
          <p className="hero-description">Report potholes, flooding, damaged footpaths and other public infrastructure problems. Add a short video and pin the location — you do not need a GPS file.</p>
          <div className="hero-trust-row"><span><ShieldCheck size={16} /> Simple to report</span><span><MapPin size={16} /> Location pin included</span><span><FileVideo2 size={16} /> Video evidence</span></div>
        </div>
        <div className="hero-side-card">
          <div className="hero-side-icon"><Construction size={22} /></div>
          <div className="hero-side-title">A clearer path from report to response</div>
          <div className="workflow-step"><span className="workflow-number">1</span><div><strong>You share the issue</strong><p>Video + location + a few details</p></div></div>
          <div className="workflow-line" />
          <div className="workflow-step"><span className="workflow-number">2</span><div><strong>Staff review the evidence</strong><p>Reports appear in a separate staff workspace</p></div></div>
          <div className="workflow-line" />
          <div className="workflow-step"><span className="workflow-number">3</span><div><strong>Follow-up is recorded</strong><p>Review status and notes stay with the report</p></div></div>
        </div>
      </section>

      {success && (
        <section className="success-banner" role="status">
          <div className="success-icon"><CheckCircle2 size={26} /></div>
          <div className="success-copy"><h2>Report received</h2><p>{success.message}</p><div className="report-reference"><span>YOUR REFERENCE NUMBER</span><strong>{success.id}</strong></div></div>
          <button className="icon-button success-close" aria-label="Dismiss confirmation" onClick={() => setSuccess(null)}>×</button>
        </section>
      )}

      <form ref={formRef} onSubmit={submitReport} className="report-form">
        <div className="form-topline"><div><div className="section-kicker">NEW REPORT</div><h2>Tell us what needs attention</h2></div><div className="required-note"><span>*</span> Required fields</div></div>
        <div className="report-layout">
          <div className="form-column form-details-column">
            <section className="form-card">
              <div className="section-heading"><div className="section-icon icon-indigo"><CircleAlert size={19} /></div><div><h3>About the problem</h3><p>Clear details help staff review your report faster.</p></div></div>
              <div className="field-group"><label htmlFor="issue_type">Type of problem <span className="required-mark">*</span></label><select id="issue_type" value={issueType} onChange={(e) => setIssueType(e.target.value)}>{ISSUE_TYPES.map((type) => <option key={type}>{type}</option>)}</select></div>
              <div className="field-group"><label htmlFor="title">Short title <span className="required-mark">*</span></label><input id="title" name="title" required maxLength={160} placeholder="e.g. Deep pothole near the main bus stop" /></div>
              <div className="field-group"><label htmlFor="description">What did you notice? <span className="label-optional">Optional</span></label><textarea id="description" name="description" maxLength={3000} rows={4} placeholder="Describe the danger, direction of travel, nearby landmark or whether the road is blocked." /></div>
              <div className="field-row">
                <div className="field-group"><label htmlFor="camera_source">Video source</label><select id="camera_source" value={cameraSource} onChange={(e) => setCameraSource(e.target.value)}><option>Phone / dashcam</option><option>Street / CCTV camera</option><option>Public transport camera</option><option>Other camera</option></select></div>
                <div className="field-group"><label htmlFor="camera_id">Camera ID <span className="label-optional">Optional</span></label><input id="camera_id" name="camera_id" maxLength={100} placeholder="e.g. CAM-12 / junction name" /></div>
              </div>
              <div className="field-row">
                <div className="field-group"><label htmlFor="reporter_name">Your name <span className="label-optional">Optional</span></label><input id="reporter_name" name="reporter_name" maxLength={100} placeholder="Name" autoComplete="name" /></div>
                <div className="field-group"><label htmlFor="contact">Contact for follow-up <span className="label-optional">Optional</span></label><input id="contact" name="contact" maxLength={160} placeholder="Email or phone" autoComplete="email" /></div>
              </div>
            </section>

            <section className="form-card evidence-card">
              <div className="section-heading"><div className="section-icon icon-teal"><Video size={19} /></div><div><h3>Show the problem</h3><p>A short video is enough to send a report. GPS is not required.</p></div></div>
              <label className={`video-dropzone ${video ? 'video-dropzone-selected' : ''}`}>
                <input type="file" accept="video/mp4,video/webm,video/quicktime,video/x-msvideo,video/x-matroska,.mkv" onChange={(e) => handleVideo(e.target.files?.[0])} hidden />
                <div className="upload-icon"><Upload size={23} /></div>
                {video ? <><strong className="file-selected-name">{video.name}</strong><span>{(video.size / (1024 * 1024)).toFixed(1)} MB · Click to replace video</span></> : <><strong>Choose a video to upload</strong><span>Click here or drop a video file · MP4, MOV, WebM, AVI or MKV</span><em>Maximum file size: 500 MB</em></>}
              </label>
              <div className="privacy-hint"><ShieldCheck size={16} /><span>Only share footage you are allowed to provide. Avoid including private conversations or unnecessary close-ups of people.</span></div>
              <button type="button" className="advanced-toggle" onClick={() => setAdvanced(!advanced)}>{advanced ? '− Hide' : '+ Add optional GPS track'} <span>For dashboard/dashcam recordings that have a GPX or CSV route file</span></button>
              {advanced && <div className="gps-upload-row"><label className="gps-file-control"><Gauge size={17} /><span>{gps ? gps.name : 'Choose GPX / CSV file'}</span><input type="file" accept=".gpx,.csv" onChange={(e) => handleGps(e.target.files?.[0])} /></label>{gps && <button className="text-action" type="button" onClick={() => setGps(null)}>Remove</button>}<p>The route file can help staff estimate where an issue appears in the video. It is optional.</p></div>}
            </section>
          </div>

          <div className="form-column form-location-column">
            <LocationPicker location={location} onChange={(nextLocation) => { setLocation(nextLocation); setLocationConfirmed(false); }} onUseCurrentLocation={useCurrentLocation} locating={locating} />
            <label className="location-confirm-row"><input type="checkbox" checked={locationConfirmed} onChange={(event) => setLocationConfirmed(event.target.checked)} disabled={!location} /><span><strong>I checked the pin.</strong> It marks the actual problem location, not my home or current position unless the problem is there.</span></label>
            {locationNotice && <div className="location-status-note" role="status">{locationNotice}</div>}
            <div className="location-note"><CircleHelp size={17} /><div><strong>How to get a useful location</strong><p>Use your device location while near the problem, or click and drag the pin onto the exact spot. Browser permission may be required.</p></div></div>
            <div className="submit-card">
              {error && <div className="inline-error" role="alert"><CircleAlert size={17} /><span>{error}</span></div>}
              <label className="consent-row"><input type="checkbox" name="consent" required /> <span>I confirm I am allowed to share this video as evidence. <b>*</b></span></label>
              <button className="button button-primary submit-button" type="submit" disabled={submitting}>
                {submitting ? <><LoaderCircle size={18} className="spin" /> Sending report…</> : <>Send infrastructure report <ArrowRight size={18} /></>}
              </button>
              <div className="submit-footnote"><ShieldCheck size={14} /> Your report is marked unverified until staff review it.</div>
            </div>
          </div>
        </div>
      </form>
      <section className="how-it-works-strip"><div className="mini-benefit"><div className="mini-benefit-icon"><MapPin size={18} /></div><div><strong>Location first</strong><p>Device GPS or a map pin</p></div></div><div className="mini-benefit"><div className="mini-benefit-icon"><Video size={18} /></div><div><strong>Evidence attached</strong><p>Video uploads to the report record</p></div></div><div className="mini-benefit"><div className="mini-benefit-icon"><FileCheck2 size={18} /></div><div><strong>Staff review</strong><p>Every report needs human validation</p></div></div></section>
    </main>
  );
}
