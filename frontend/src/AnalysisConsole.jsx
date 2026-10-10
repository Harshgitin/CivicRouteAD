import React, { useState, useEffect, useCallback, useMemo } from 'react';
import Header from './components/Header';
import VideoPlayerHUD from './components/VideoPlayerHUD';
import MapDashboard from './components/MapDashboard';
import HazardList from './components/HazardList';
import AnalyticsPanel from './components/AnalyticsPanel';
import UploadModal from './components/UploadModal';
import ReportModal from './components/ReportModal';
import { 
  fetchScenarios, 
  previewScenario, 
  fetchGeoJSON, 
  fetchTelemetry,
  fetchRunStatus
} from './utils/api';
import { Loader2, ShieldCheck, AlertCircle } from 'lucide-react';

export default function AnalysisConsole() {
  const [scenarios, setScenarios] = useState([]);
  const [selectedScenario, setSelectedScenario] = useState('scenario_storm_debris');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);

  const [runData, setRunData] = useState(null);
  const [geojsonData, setGeojsonData] = useState(null);
  const [telemetry, setTelemetry] = useState([]);
  const [currentTime, setCurrentTime] = useState(0);
  const [selectedHazard, setSelectedHazard] = useState(null);
  const [liveHazards, setLiveHazards] = useState([]);

  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [isReportOpen, setIsReportOpen] = useState(false);

  // Initial Load: Fetch scenarios and run primary benchmark
  useEffect(() => {
    fetchScenarios()
      .then((res) => {
        setScenarios(res.scenarios || []);
        if (res.scenarios && res.scenarios.length > 0) {
          loadScenario(res.scenarios[0].id);
        }
      })
      .catch((err) => {
        console.error('Error fetching scenarios:', err);
        setErrorMessage('Unable to connect to CivicRouteAD backend server.');
      });
  }, []);

  const loadScenario = async (scId) => {
    setIsLoading(true);
    setErrorMessage(null);
    setSelectedScenario(scId);

    try {
      const result = await previewScenario(scId);
      setRunData(result);

      // Load associated GeoJSON and Telemetry
      const [gData, tData] = await Promise.all([
        fetchGeoJSON(result.run_id),
        fetchTelemetry(result.run_id)
      ]);

      setGeojsonData(gData);
      setTelemetry(tData);
      setCurrentTime(0);
      setSelectedHazard(null);
      setLiveHazards([]);
      setIsLoading(false);
    } catch (err) {
      console.error('Failed to process scenario:', err);
      setErrorMessage(err.message || 'Error processing scenario');
      setIsLoading(false);
    }
  };

  const handleUploadSuccess = async (result) => {
    setIsLoading(true);
    setErrorMessage(null);

    try {
      // Fetch the uploaded run's GIS and telemetry before switching the player.
      // This prevents a frame or two of old demo GPS/detection overlays appearing
      // over the newly uploaded clip.
      const [gData, tData] = await Promise.all([
        fetchGeoJSON(result.run_id),
        fetchTelemetry(result.run_id)
      ]);
      setRunData(result);
      setLiveHazards([]);
      setGeojsonData(gData);
      setTelemetry(tData);
      setCurrentTime(0);
      setSelectedHazard(null);
    } catch (err) {
      console.error('Error loading uploaded artifacts:', err);
      setErrorMessage(err.message || 'The uploaded video was processed, but its telemetry/GIS artifacts could not be loaded.');
    } finally {
      setIsLoading(false);
    }
  };

  // GPS uploads are analyzed in the background so the selected video can
  // appear immediately and perform frame-by-frame AI while the GIS layer builds.
  useEffect(() => {
    const runId = runData?.run_id;
    if (!runId || runData?.status !== 'processing') return undefined;

    let cancelled = false;
    let timerId = null;
    const pollStatus = async () => {
      try {
        const status = await fetchRunStatus(runId);
        if (cancelled) return;
        if (status.status === 'completed') {
          const [gData, tData] = await Promise.all([
            fetchGeoJSON(runId),
            fetchTelemetry(runId)
          ]);
          if (cancelled) return;
          setGeojsonData(gData);
          setTelemetry(tData);
          setLiveHazards([]);
          setRunData((previous) => {
            if (!previous || previous.run_id !== runId) return previous;
            return {
              ...previous,
              ...(status.result || {}),
              analysis_progress: 100,
              analysis_message: status.message || 'Full-video analysis complete; saved pothole outlines are ready.',
              video_url: previous.video_url,
              video_playback_warning: previous.video_playback_warning,
              video_playback_format: previous.video_playback_format,
              status: 'completed'
            };
          });
        } else if (status.status === 'failed') {
          setErrorMessage(status.message || 'Background GIS analysis failed. Live video inference may still be available.');
          setRunData((previous) => previous?.run_id === runId ? { ...previous, status: 'failed' } : previous);
          } else {
          // Show the true background scan progress in the video panel without
          // blocking playback or changing the surrounding Analysis Lab layout.
          setRunData((previous) => previous?.run_id === runId ? {
            ...previous,
            status: 'processing',
            analysis_progress: Number.isFinite(Number(status.progress_percent))
              ? Number(status.progress_percent)
              : previous.analysis_progress,
            analysis_message: status.message || previous.analysis_message,
            analysis_sampled_frames: status.sampled_frames ?? previous.analysis_sampled_frames,
              analysis_total_frames: status.total_frames ?? previous.analysis_total_frames,
          } : previous);
          timerId = window.setTimeout(pollStatus, 2000);
        }
      } catch (err) {
        if (!cancelled) {
          // Transient status errors should not stop video playback; retry a few seconds later.
          timerId = window.setTimeout(pollStatus, 3000);
          console.warn('GIS background status check will retry:', err);
        }
      }
    };

    pollStatus();
    return () => {
      cancelled = true;
      if (timerId !== null) window.clearTimeout(timerId);
    };
  }, [runData?.run_id, runData?.status]);

  // Merge live, GPS-anchored video detections into the existing map and list.
  // Close detections of the same class are merged into one transient live marker.
  const handleLiveInference = useCallback((result) => {
    const candidates = (result?.detections || []).filter((item) =>
      Number.isFinite(item.lat) && Number.isFinite(item.lon)
      && Math.abs(item.lat) <= 90 && Math.abs(item.lon) <= 180
    );
    if (!candidates.length) return;

    setLiveHazards((previous) => {
      const next = [...previous];
      const distanceMeters = (a, b) => {
        const latScale = 111320;
        const lonScale = 111320 * Math.cos(((a.lat + b.lat) / 2) * Math.PI / 180);
        return Math.hypot((a.lat - b.lat) * latScale, (a.lon - b.lon) * lonScale);
      };

      candidates.forEach((item) => {
        const candidate = {
          id: `LIVE-${item.type}-${Number(item.timestamp_sec ?? result.timestamp_sec ?? 0).toFixed(1).replace('.', '-')}-${Number(item.lat).toFixed(5)}`,
          type: item.type || 'unknown_hazard',
          label: item.label || (item.type || 'Road hazard').replace(/_/g, ' '),
          severity: item.severity || 'Medium',
          confidence: Number(item.conf) || 0,
          source: item.source || 'live_frame_inference',
          verification: item.verification || 'provisional_heuristic',
          lat: item.lat,
          lon: item.lon,
          location_quality: item.location_quality || 'approximate_live_camera_projection',
          estimated_uncertainty_m: item.estimated_uncertainty_m ?? null,
          forward_distance_m: item.forward_distance_m ?? null,
          lateral_offset_m: item.lateral_offset_m ?? null,
          lane_location: item.lane_location || 'Estimated road area',
          timestamp_sec: Number(item.timestamp_sec ?? result.timestamp_sec ?? 0),
          duration_visible_sec: 0,
          snapshot_url: '',
          is_live: true,
        };
        const matchIndex = next.findIndex((old) => old.type === candidate.type && distanceMeters(old, candidate) < 12);
        if (matchIndex >= 0) next[matchIndex] = { ...next[matchIndex], ...candidate, id: next[matchIndex].id };
        else next.push(candidate);
      });
      return next.slice(-80);
    });
  }, []);

  const displayHazards = useMemo(() => {
    const processed = runData?.hazards || [];
    return [...processed, ...liveHazards.filter((live) => !processed.some((saved) =>
      saved.type === live.type && Number.isFinite(saved.lat) && Number.isFinite(saved.lon)
      && Math.abs(saved.lat - live.lat) < 0.00008 && Math.abs(saved.lon - live.lon) < 0.00008
    ))];
  }, [runData?.hazards, liveHazards]);

  const displayGeoJSON = useMemo(() => {
    const base = geojsonData || { type: 'FeatureCollection', features: [] };
    const liveFeatures = liveHazards.filter((h) => Number.isFinite(h.lat) && Number.isFinite(h.lon)).map((h) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [h.lon, h.lat] },
      properties: {
        feature_class: 'road_hazard', hazard_id: h.id, label: h.label,
        severity: h.severity, marker_color: h.severity === 'Critical' ? '#ef4444' : '#f59e0b',
        forward_distance_m: h.forward_distance_m, lateral_offset_m: h.lateral_offset_m,
        lane_location: h.lane_location, location_quality: h.location_quality,
        suggested_action: 'Live model prediction — validate this estimated location before dispatch.',
        snapshot_url: '', source: h.source, confidence: h.confidence, is_live: true
      }
    }));
    const baseFeatures = Array.isArray(base.features) ? base.features : [];
    return { ...base, type: 'FeatureCollection', features: [...baseFeatures, ...liveFeatures] };
  }, [geojsonData, liveHazards]);

  const handleSeekToHazard = (hazard) => {
    setSelectedHazard(hazard);
    if (hazard && typeof hazard.timestamp_sec === 'number') {
      setCurrentTime(hazard.timestamp_sec);
    }
  };

  const currentTelPoint = telemetry.find(
    (t) => Math.abs(t.time_sec - currentTime) < 0.25
  ) || telemetry[0];

  return (
    <div className="min-h-screen bg-[#0a0f1d] text-slate-100 flex flex-col font-sans">
      
      {/* Top Navigation */}
      <Header
        scenarios={scenarios}
        selectedScenario={selectedScenario}
        onSelectScenario={loadScenario}
        isLoading={isLoading}
        onOpenUpload={() => setIsUploadOpen(true)}
        onOpenReport={() => setIsReportOpen(true)}
        runData={runData}
      />

      {/* Main Body */}
      <main className="flex-1 p-4 max-w-[1920px] w-full mx-auto flex flex-col gap-4">
        
        {/* Loading Overlay */}
        {isLoading && (
          <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex flex-col items-center justify-center gap-3">
            <Loader2 className="w-10 h-10 text-cyan-400 animate-spin" />
            <div className="text-sm font-bold text-white tracking-wide">
              PREPARING ANALYSIS LAB...
            </div>
            <div className="text-xs font-mono text-slate-400">
              Loading road-survey preview • Full AI/GIS analysis runs in the background
            </div>
          </div>
        )}

        {/* Error notification if any */}
        {errorMessage && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 text-xs text-red-400 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{errorMessage}</span>
            </div>
            <button 
              onClick={() => setErrorMessage(null)}
              className="text-slate-400 hover:text-white"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Row 1: Dual Synchronized Console (Video Player HUD + Interactive GIS Map) */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-stretch">
          
          {/* Left: Video Player with AR Bounding Box & HUD */}
          <div className="flex flex-col">
            <VideoPlayerHUD
              videoUrl={runData?.video_url || ''}
              telemetry={telemetry}
              hazards={displayHazards}
              currentTime={currentTime}
              onTimeUpdate={setCurrentTime}
              onSelectHazard={handleSeekToHazard}
              playbackWarning={runData?.video_playback_warning || null}
              onOpenUpload={() => setIsUploadOpen(true)}
              isSynthetic={Boolean(runData?.is_synthetic)}
              sourceName={runData?.metadata?.video_filename || 'Demo road-survey footage'}
              // Uploaded footage gets live frame inference while the deep scan runs.
              // The upload endpoint's real status is "processing"; allowing this
              // status is essential so boxes appear before batch analysis completes.
              // On completion, playback switches to the denser saved full-video detections.
              liveInferenceEnabled={Boolean(
                runData && runData.video_url
              )}
              runId={runData?.run_id || null}
              onLiveInference={handleLiveInference}
              analysisStatus={runData?.status || null}
              analysisProgress={runData?.analysis_progress ?? null}
              analysisMessage={runData?.analysis_message || null}
            />
          </div>

          {/* Right: Leaflet Interactive GIS Map */}
          <div className="flex flex-col">
            <MapDashboard
              geojsonData={displayGeoJSON}
              hazards={displayHazards}
              currentTelemetry={currentTelPoint}
              selectedHazard={selectedHazard}
              onSelectHazard={setSelectedHazard}
              onSeekToHazard={handleSeekToHazard}
            />
          </div>

        </div>

        {/* Row 2: Analytics & Incident Register */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          
          {/* Analytics Panel (2 cols on large screen) */}
          <div className="lg:col-span-2">
            <AnalyticsPanel runData={runData} />
          </div>

          {/* Incident Feed */}
          <div className="lg:col-span-1">
            <HazardList
              hazards={displayHazards}
              selectedHazard={selectedHazard}
              onSelectHazard={setSelectedHazard}
              onSeekToHazard={handleSeekToHazard}
            />
          </div>

        </div>

      </main>

      {/* Footer */}
      <footer className="border-t border-slate-900 bg-[#0d1326] px-4 py-3 text-center text-xs text-slate-500 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-bold text-slate-300">CivicRouteAD</span>
          <span>•</span>
          <span>Automated Road Obstruction & Hazard Mapping</span>
        </div>
        <div className="font-mono text-[11px] text-slate-500">
          Ref: Sekilab RoadDamageDetector &amp; comma2k19 • Edge-to-GIS Photogrammetry Pipeline
        </div>
      </footer>

      {/* Modals */}
      <UploadModal
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        onUploadSuccess={handleUploadSuccess}
      />

      <ReportModal
        isOpen={isReportOpen}
        onClose={() => setIsReportOpen(false)}
        runId={runData?.run_id}
      />

    </div>
  );
}
