import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, AlertCircle, ArrowUpRight, CheckCircle2, CircleDot, Clock3,
  FileVideo2, Filter, KeyRound, LoaderCircle, LogOut, MapPin, MessageSquareText,
  Play, RefreshCw, Search, ShieldCheck, UserRound, Video, XCircle, ClipboardCheck,
  Download, Siren, Camera, Trash2
} from 'lucide-react';
import ReportLocationEditor from './ReportLocationEditor';
import ReportsMap from './ReportsMap';

const STATUSES = ['New', 'Reviewing', 'Assigned', 'Resolved', 'Duplicate', 'Invalid'];
const STATUS_CLASS = {
  New: 'status-new', Reviewing: 'status-reviewing', Assigned: 'status-assigned',
  Resolved: 'status-resolved', Duplicate: 'status-muted', Invalid: 'status-muted'
};

function prettyDate(value) {
  if (!value) return 'Date unavailable';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString([], { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatBytes(value) {
  if (!Number.isFinite(Number(value))) return '—';
  const bytes = Number(value);
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

async function staffRequest(path, session, options = {}) {
  const headers = { ...(options.headers || {}), 'X-Staff-Session': session };
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response;
}

export default function StaffReportsPage() {
  const [session, setSession] = useState(() => sessionStorage.getItem('civicroute_staff_session') || '');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loginLoading, setLoginLoading] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [developmentWarning, setDevelopmentWarning] = useState(false);
  const [reports, setReports] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [detail, setDetail] = useState(null);
  const [loadingReports, setLoadingReports] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState('');
  const [actionError, setActionError] = useState('');
  const [statusFilter, setStatusFilter] = useState('All reports');
  const [search, setSearch] = useState('');
  const [note, setNote] = useState('');
  const [assignee, setAssignee] = useState('');
  const [evidenceUrl, setEvidenceUrl] = useState('');
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState('');
  const [gpsLoading, setGpsLoading] = useState(false);
  const [toast, setToast] = useState('');

  const loadReports = useCallback(async (activeSession = session) => {
    if (!activeSession) return;
    setLoadingReports(true);
    setActionError('');
    try {
      const response = await staffRequest('/api/staff/reports', activeSession);
      const data = await response.json();
      const nextReports = data.reports || [];
      setReports(nextReports);
      setSelectedId((current) => current && nextReports.some((r) => r.id === current) ? current : (nextReports[0]?.id || ''));
      if (!nextReports.length) setDetail(null);
    } catch (err) {
      setActionError(err.message);
      if (err.message.toLowerCase().includes('sign in')) {
        sessionStorage.removeItem('civicroute_staff_session');
        setSession('');
      }
    } finally { setLoadingReports(false); }
  }, [session]);

  const loadDetail = useCallback(async (id, activeSession = session) => {
    if (!activeSession || !id) { setDetail(null); return; }
    setDetailLoading(true);
    setActionError('');
    try {
      const response = await staffRequest(`/api/staff/reports/${encodeURIComponent(id)}`, activeSession);
      const data = await response.json();
      setDetail(data);
      setAssignee(data.assigned_to || '');
    } catch (err) { setActionError(err.message); }
    finally { setDetailLoading(false); }
  }, [session]);

  useEffect(() => { if (session) loadReports(session); }, [session, loadReports]);
  useEffect(() => { if (session && selectedId) loadDetail(selectedId, session); }, [session, selectedId, loadDetail]);
  useEffect(() => () => { if (evidenceUrl) URL.revokeObjectURL(evidenceUrl); }, [evidenceUrl]);

  const signIn = async (event) => {
    event.preventDefault(); setLoginLoading(true); setLoginError('');
    try {
      const response = await fetch('/api/staff/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Could not sign in.');
      sessionStorage.setItem('civicroute_staff_session', data.session);
      setDevelopmentWarning(Boolean(data.development_password_warning));
      setSession(data.session); setPassword('');
    } catch (err) { setLoginError(err.message); }
    finally { setLoginLoading(false); }
  };

  const signOut = async () => {
    try { if (session) await staffRequest('/api/staff/logout', session, { method: 'POST' }); } catch {}
    sessionStorage.removeItem('civicroute_staff_session');
    setSession(''); setReports([]); setDetail(null); setSelectedId(''); setEvidenceUrl('');
  };

  const visibleReports = useMemo(() => reports.filter((report) => {
    const matchesStatus = statusFilter === 'All reports' || report.status === statusFilter;
    const query = search.trim().toLowerCase();
    const matchesSearch = !query || [report.id, report.title, report.issue_type, report.landmark, report.status].some((value) => String(value || '').toLowerCase().includes(query));
    return matchesStatus && matchesSearch;
  }), [reports, search, statusFilter]);

  const metrics = useMemo(() => ({
    total: reports.length,
    newCount: reports.filter((report) => report.status === 'New').length,
    inProgress: reports.filter((report) => ['Reviewing', 'Assigned'].includes(report.status)).length,
    closed: reports.filter((report) => ['Resolved', 'Duplicate', 'Invalid'].includes(report.status)).length,
  }), [reports]);

  const deleteReport = async (report) => {
    if (!report?.id || actionLoading) return;
    const title = String(report.title || 'Untitled report').slice(0, 100);
    const confirmed = window.confirm(`Permanently delete report ${report.id} — "${title}"?\n\nThis also deletes its uploaded video, optional GPS file, and analysis artifacts. This action cannot be undone.`);
    if (!confirmed) return;
    setActionLoading('delete'); setActionError('');
    try {
      await staffRequest(`/api/staff/reports/${encodeURIComponent(report.id)}`, session, { method: 'DELETE' });
      if (evidenceUrl) URL.revokeObjectURL(evidenceUrl);
      setEvidenceUrl(''); setEvidenceError(''); setDetail(null); setSelectedId(''); setNote(''); setAssignee('');
      await loadReports(session);
      setToast(`Report ${report.id} and its stored evidence were deleted.`); window.setTimeout(() => setToast(''), 3200);
    } catch (err) { setActionError(err.message); }
    finally { setActionLoading(''); }
  };

  const clearAllReports = async () => {
    if (!reports.length || actionLoading) return;
    const confirmed = window.confirm(`Permanently clear all ${reports.length} resident report(s), including their uploaded videos, GPS files, notes, and analysis artifacts?\n\nDemo scenarios and benchmark runs will not be deleted. This action cannot be undone.`);
    if (!confirmed) return;
    setActionLoading('clear'); setActionError('');
    try {
      const response = await staffRequest('/api/staff/reports', session, { method: 'DELETE' });
      const result = await response.json().catch(() => ({}));
      if (evidenceUrl) URL.revokeObjectURL(evidenceUrl);
      setEvidenceUrl(''); setEvidenceError(''); setReports([]); setSelectedId(''); setDetail(null); setNote(''); setAssignee('');
      setToast(`Cleared ${result.deleted_count ?? reports.length} report(s) and their stored evidence.`); window.setTimeout(() => setToast(''), 3200);
    } catch (err) { setActionError(err.message); }
    finally { setActionLoading(''); }
  };

  const updateReport = async (updates, successText = 'Report updated.') => {
    if (!detail) return;
    setActionLoading('update'); setActionError('');
    try {
      await staffRequest(`/api/staff/reports/${encodeURIComponent(detail.id)}`, session, { method: 'PATCH', body: JSON.stringify(updates) });
      await Promise.all([loadReports(session), loadDetail(detail.id, session)]);
      setToast(successText); window.setTimeout(() => setToast(''), 2800);
    } catch (err) { setActionError(err.message); }
    finally { setActionLoading(''); }
  };

  const runAnalysis = async () => {
    if (!detail) return;
    setActionLoading('analysis'); setActionError('');
    try {
      const response = await staffRequest(`/api/staff/reports/${encodeURIComponent(detail.id)}/analyze`, session, { method: 'POST' });
      const result = await response.json();
      await Promise.all([loadReports(session), loadDetail(detail.id, session)]);
      setToast(`Video analysis finished: ${result.analysis?.hazards_count ?? 0} preliminary finding(s).`); window.setTimeout(() => setToast(''), 3500);
    } catch (err) { setActionError(err.message); }
    finally { setActionLoading(''); }
  };

  const loadEvidence = async () => {
    if (!detail) return;
    setEvidenceLoading(true); setEvidenceError('');
    try {
      if (evidenceUrl) URL.revokeObjectURL(evidenceUrl);
      setEvidenceUrl('');
      const response = await staffRequest(`/api/staff/reports/${encodeURIComponent(detail.id)}/evidence`, session);
      const blob = await response.blob();
      setEvidenceUrl(URL.createObjectURL(blob));
    } catch (err) { setEvidenceError(err.message); }
    finally { setEvidenceLoading(false); }
  };

  const downloadAnalysis = async () => {
    if (!detail?.analysis) return;
    setActionLoading('export'); setActionError('');
    try {
      const response = await staffRequest(`/api/staff/reports/${encodeURIComponent(detail.id)}/analysis/export`, session);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url; link.download = `${detail.id}-analysis.json`; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) { setActionError(err.message); }
    finally { setActionLoading(''); }
  };

  const downloadGps = async () => {
    if (!detail?.gps_download_url) return;
    setGpsLoading(true); setActionError('');
    try {
      const response = await staffRequest(detail.gps_download_url, session);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a'); link.href = url; link.download = detail.gps_name || `${detail.id}-track.gpx`; link.click(); URL.revokeObjectURL(url);
    } catch (err) { setActionError(err.message); }
    finally { setGpsLoading(false); }
  };

  if (!session) return (
    <main className="staff-login-page page-shell">
      <div className="staff-login-illustration"><div className="login-glow" /><div className="login-brand-icon"><ShieldCheck size={28} /></div><div className="section-kicker">AUTHORIZED WORKSPACE</div><h1>Public works,<br /><span>with better visibility.</span></h1><p>Review resident submissions, inspect evidence, map incidents, and record follow-up in one secure workspace.</p><div className="login-feature"><ClipboardCheck size={18} /><span>One report record from submission to resolution</span></div><div className="login-feature"><MapPin size={18} /><span>Location pins and video evidence together</span></div><div className="login-feature"><Activity size={18} /><span>Preliminary AI analysis with human review</span></div></div>
      <form className="staff-login-card" onSubmit={signIn}><div className="login-lock-icon"><KeyRound size={22} /></div><h2>Staff sign in</h2><p>This area is for authorized handlers and administrators only.</p>{loginError && <div className="inline-error"><AlertCircle size={16} />{loginError}</div>}<div className="field-group"><label htmlFor="staff-password">Staff password</label><div className="password-field"><input id="staff-password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Enter staff password" required /><button type="button" onClick={() => setShowPassword(!showPassword)}>{showPassword ? 'Hide' : 'Show'}</button></div></div><button className="button button-primary submit-button" disabled={loginLoading}>{loginLoading ? <><LoaderCircle size={18} className="spin" /> Checking access…</> : <>Open staff console <ArrowUpRight size={18} /></>}</button><div className="login-privacy"><ShieldCheck size={15} /> Session expires after 8 hours. Never share this login.</div></form>
    </main>
  );

  return (
    <main className="staff-page page-shell">
      <section className="staff-page-heading"><div><div className="section-kicker">STAFF OPERATIONS</div><h1>Infrastructure report desk</h1><p>Review submitted problems, inspect the location and footage, then record the next action.</p></div><div className="staff-heading-actions"><button className="button button-danger" onClick={clearAllReports} disabled={!reports.length || loadingReports || Boolean(actionLoading)} title="Permanently delete all resident reports and their uploaded evidence"><Trash2 size={16} /> Clear all reports</button><button className="button button-secondary" onClick={() => loadReports(session)} disabled={loadingReports || Boolean(actionLoading)}><RefreshCw size={16} className={loadingReports ? 'spin' : ''} /> Refresh reports</button><button className="button button-quiet" onClick={signOut}><LogOut size={16} /> Sign out</button></div></section>
      {developmentWarning && <div className="security-warning"><AlertCircle size={17} /><div><strong>Development password is active.</strong> Before using this outside your laptop, set the <code>CIVICROUTE_STAFF_PASSWORD</code> environment variable to a strong private password and restart the server.</div><button aria-label="Dismiss warning" onClick={() => setDevelopmentWarning(false)}><XCircle size={17} /></button></div>}
      {actionError && <div className="inline-error page-error"><AlertCircle size={17} /><span>{actionError}</span><button onClick={() => setActionError('')}>Dismiss</button></div>}

      <section className="staff-metrics-grid">
        <div className="staff-metric-card"><div className="metric-icon metric-blue"><FileVideo2 size={18} /></div><div><span>Total reports</span><strong>{metrics.total}</strong><small>Citizen submissions</small></div></div>
        <div className="staff-metric-card"><div className="metric-icon metric-orange"><Siren size={18} /></div><div><span>New reports</span><strong>{metrics.newCount}</strong><small>Need initial review</small></div></div>
        <div className="staff-metric-card"><div className="metric-icon metric-purple"><Clock3 size={18} /></div><div><span>In progress</span><strong>{metrics.inProgress}</strong><small>Reviewing or assigned</small></div></div>
        <div className="staff-metric-card"><div className="metric-icon metric-green"><CheckCircle2 size={18} /></div><div><span>Closed</span><strong>{metrics.closed}</strong><small>Resolved or closed out</small></div></div>
      </section>

      <section className="staff-workspace-grid">
        <div className="staff-panel report-queue-panel">
          <div className="panel-heading"><div><h2>Report queue</h2><p>{visibleReports.length} {visibleReports.length === 1 ? 'report' : 'reports'} shown</p></div><span className="small-live-dot">LIVE DATA</span></div>
          <div className="queue-search-row"><div className="search-input-wrap"><Search size={17} /><input aria-label="Search reports" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search title, type, landmark or ID" /></div><div className="queue-filter"><Filter size={15} /><select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter by status"><option>All reports</option>{STATUSES.map((status) => <option key={status}>{status}</option>)}</select></div></div>
          <div className="report-queue-list">
            {loadingReports && !reports.length ? <div className="queue-empty"><LoaderCircle className="spin" size={25} /><strong>Loading reports</strong><p>Getting the latest resident submissions.</p></div> : visibleReports.length === 0 ? <div className="queue-empty"><div className="queue-empty-icon"><ClipboardCheck size={24} /></div><strong>{reports.length ? 'No matching reports' : 'No citizen reports yet'}</strong><p>{reports.length ? 'Try changing the search or status filter.' : 'Once someone submits a report from the public page, it will appear here. Test submissions are stored separately from demo scenarios.'}</p></div> : visibleReports.map((report) => (
              <button key={report.id} type="button" onClick={() => { setSelectedId(report.id); setEvidenceUrl(''); }} className={`report-queue-item ${selectedId === report.id ? 'report-queue-item-selected' : ''}`}>
                <div className="queue-item-top"><span className="queue-report-id">{report.id}</span><span className={`status-pill ${STATUS_CLASS[report.status] || 'status-muted'}`}>{report.status || 'New'}</span></div>
                <strong className="queue-item-title">{report.title}</strong><span className="queue-item-type">{report.issue_type}</span>
                <div className="queue-item-bottom"><span><MapPin size={13} />{report.landmark || `${Number(report.latitude).toFixed(4)}, ${Number(report.longitude).toFixed(4)}`}</span><time>{prettyDate(report.created_at)}</time></div>
              </button>
            ))}
          </div>
        </div>

        <div className="staff-panel report-detail-panel">
          {!selectedId ? <div className="detail-empty"><div className="queue-empty-icon"><MapPin size={24} /></div><h2>Select a report to review</h2><p>Choose an incident from the queue to see its location, video, notes and analysis.</p></div> : detailLoading && !detail ? <div className="detail-empty"><LoaderCircle size={28} className="spin" /><p>Opening report…</p></div> : detail ? <>
            <div className="panel-heading detail-panel-heading"><div><div className="queue-report-id">{detail.id} · {prettyDate(detail.created_at)}</div><h2>{detail.title}</h2><p>{detail.issue_type}</p></div><div className="detail-heading-actions"><span className={`status-pill ${STATUS_CLASS[detail.status] || 'status-muted'}`}>{detail.status || 'New'}</span><button type="button" className="button button-danger button-small" onClick={() => deleteReport(detail)} disabled={Boolean(actionLoading)}><Trash2 size={14} /> Delete report</button></div></div>
            <div className="detail-summary-grid"><div><span>LOCATION</span><strong><MapPin size={15} />{detail.landmark || 'Pinned map location'}</strong><small>{Number(detail.latitude).toFixed(6)}, {Number(detail.longitude).toFixed(6)}</small></div><div><span>EVIDENCE</span><strong><Video size={15} />{detail.video_name || 'Video attached'}</strong><small>{formatBytes(detail.video_size_bytes)}{detail.has_gps ? ' · GPS track attached' : ' · No GPS track'}</small></div></div>
            <div className="report-description-block"><span className="detail-label">REPORT DETAILS</span><p>{detail.description || 'No extra description was provided.'}</p><div className="detail-meta-row"><span><Camera size={14} /> {detail.camera_source || 'Source not specified'}{detail.camera_id ? ` · ${detail.camera_id}` : ''}</span><span><UserRound size={14} /> {detail.reporter_name || 'Anonymous report'}</span></div>{detail.contact && <div className="contact-line">Contact for follow-up: <strong>{detail.contact}</strong></div>}</div>

            <div className="review-section-heading"><div><h3>Location &amp; evidence</h3><p>Reported incident pin shown on the map. GPS video projections appear only when a GPS track is available.</p></div>{detail.gps_download_url && <button className="text-action" type="button" onClick={downloadGps} disabled={gpsLoading}>{gpsLoading ? <LoaderCircle size={14} className="spin" /> : <Download size={14} />} Download GPS</button>}</div>
            <ReportsMap reports={reports} selectedReport={detail} onSelectReport={(id) => { setSelectedId(id); setEvidenceUrl(''); }} />
            <ReportLocationEditor
              key={detail.id}
              initialLocation={{ lat: Number(detail.latitude), lon: Number(detail.longitude) }}
              saving={actionLoading === 'update'}
              onSave={(point) => updateReport({ latitude: point.lat, longitude: point.lon, location_source: 'staff_corrected' }, 'Incident location corrected and saved.')}
            />
            <div className="evidence-viewer">
              <div className="evidence-viewer-top"><div><strong><FileVideo2 size={16} /> Submitted video</strong><span>Loaded only when a staff member opens it</span></div>{!evidenceUrl && <button type="button" className="button button-secondary button-small" onClick={loadEvidence} disabled={evidenceLoading}>{evidenceLoading ? <><LoaderCircle size={15} className="spin" /> Loading…</> : <><Play size={15} /> View evidence</>}</button>}</div>
              {evidenceUrl ? <video className="staff-evidence-video" controls preload="metadata" src={evidenceUrl}>Your browser does not support video playback.</video> : <div className="evidence-placeholder"><div className="evidence-play-icon"><Play size={19} /></div><span>Video evidence is private to the staff workspace</span></div>}
              {evidenceError && <p className="evidence-error">{evidenceError}</p>}
            </div>

            <div className="review-section-heading analysis-section-heading"><div><h3><Activity size={17} /> Video analysis</h3><p>Preliminary visual flags only; a staff member must verify the evidence before dispatch.</p></div><button className="button button-primary button-small" onClick={runAnalysis} disabled={actionLoading === 'analysis' || !detail.has_video}>{actionLoading === 'analysis' ? <><LoaderCircle size={15} className="spin" /> Analyzing…</> : <><Activity size={15} /> {detail.analysis ? 'Run again' : 'Analyze video'}</>}</button></div>
            {detail.analysis ? <div className="analysis-result-panel"><div className="analysis-result-top"><div><span className="analysis-status-dot" /> ANALYSIS COMPLETE · REVIEW REQUIRED</div><strong>{detail.analysis.hazards_count ?? detail.analysis.hazards?.length ?? 0} preliminary finding(s)</strong></div><p className="analysis-notice">{detail.analysis.notice || 'AI output is preliminary and unverified. Human review is required.'}</p><div className="analysis-mini-metrics"><div><span>Analysis mode</span><strong>{detail.analysis.analysis_mode === 'video_and_gps' ? 'Video + GPS track' : 'Video only'}</strong></div><div><span>Video duration</span><strong>{detail.analysis.video_duration_sec != null ? `${detail.analysis.video_duration_sec.toFixed(1)} sec` : detail.analysis.metadata?.duration_sec != null ? `${detail.analysis.metadata.duration_sec.toFixed(1)} sec` : 'Not measured'}</strong></div><div><span>Frames checked</span><strong>{detail.analysis.frames_sampled ?? 'Pipeline sample'}</strong></div></div>
                {(detail.analysis.hazards || []).length ? <div className="findings-list">{detail.analysis.hazards.map((hazard, index) => <div className="finding-item" key={hazard.id || `${hazard.type}-${index}`}><div className="finding-thumbnail">{hazard.snapshot_url ? <img src={hazard.snapshot_url} alt="Preliminary finding snapshot" /> : <CircleDot size={20} />}</div><div className="finding-main"><strong>{String(hazard.type || 'Possible hazard').replace(/_/g, ' ')}</strong><span>{hazard.id || `Finding ${index + 1}`} · {hazard.timestamp_sec != null ? `${Number(hazard.timestamp_sec).toFixed(1)} sec` : 'timestamp unavailable'}</span>{(hazard.lat != null || hazard.latitude != null) && <span className="finding-coordinates">{Number(hazard.lat ?? hazard.latitude).toFixed(6)}, {Number(hazard.lon ?? hazard.longitude).toFixed(6)}</span>}</div><div className="finding-confidence"><strong>{Math.round(Number(hazard.confidence || 0) * 100)}%</strong><span>model / heuristic score</span></div></div>)}</div> : <div className="no-findings"><CheckCircle2 size={18} /><span>No hazards were flagged in the analyzed sample. This does not prove the location is safe; staff should still inspect the report.</span></div>}
                {detail.analysis && <button className="analysis-run-link" type="button" onClick={downloadAnalysis} disabled={actionLoading === 'export'}><Download size={14} /> {actionLoading === 'export' ? 'Preparing export…' : 'Download analysis JSON'}</button>}
              </div> : <div className="analysis-empty"><Activity size={19} /><span>No analysis has been run for this report yet. Run analysis to extract possible hazards and timestamps from the submitted video.</span></div>}

            <div className="staff-action-section"><div className="review-section-heading"><div><h3><ClipboardCheck size={17} /> Review &amp; follow-up</h3><p>Record the current state and the next step.</p></div></div><div className="staff-action-form"><div className="field-group"><label htmlFor="report-status">Report status</label><select id="report-status" value={detail.status || 'New'} onChange={(e) => updateReport({ status: e.target.value }, 'Report status saved.')} disabled={actionLoading === 'update'}>{STATUSES.map((status) => <option key={status}>{status}</option>)}</select></div><div className="field-group"><label htmlFor="report-assignee">Assigned to</label><div className="assignee-save-row"><input id="report-assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)} placeholder="Team or handler" maxLength={100} /><button className="button button-secondary button-small" onClick={() => updateReport({ assigned_to: assignee }, 'Assignment saved.')} disabled={actionLoading === 'update'}>Save</button></div></div></div>
              {detail.staff_notes?.length > 0 && <div className="staff-notes-list">{detail.staff_notes.map((staffNote, index) => <div key={`${staffNote.at}-${index}`} className="staff-note-item"><MessageSquareText size={15} /><div><p>{staffNote.text}</p><time>{prettyDate(staffNote.at)}</time></div></div>)}</div>}
              <form className="note-form" onSubmit={(event) => { event.preventDefault(); if (note.trim()) { updateReport({ note }, 'Staff note added.'); setNote(''); } }}><label htmlFor="staff-note">Add internal note</label><textarea id="staff-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Sent to the road maintenance team for on-site verification…" maxLength={2000} /><button type="submit" className="button button-primary button-small" disabled={!note.trim() || actionLoading === 'update'}><MessageSquareText size={15} /> Save note</button></form>
            </div>
          </> : <div className="detail-empty"><LoaderCircle size={25} className="spin" /><p>Loading selected report…</p></div>}
        </div>
      </section>
      <div className="staff-footer-note"><ShieldCheck size={14} /> Resident reports, camera metadata and AI output are unverified until a staff handler checks them. Demo scenarios are not included in this queue.</div>
      {toast && <div className="toast-message"><CheckCircle2 size={17} /> {toast}</div>}
    </main>
  );
}
