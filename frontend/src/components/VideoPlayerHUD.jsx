import React, { useRef, useEffect, useState } from 'react';
import { detectVideoFrame } from '../utils/api';
import { interpolateDetectionBoxes } from '../utils/detectionOverlay';
import { 
  Play, 
  Pause, 
  RotateCcw, 
  Volume2, 
  VolumeX, 
  Compass, 
  Gauge, 
  AlertOctagon, 
  Maximize2,
  UploadCloud
} from 'lucide-react';

function interpolateTelemetryAtTime(points, timeSec) {
  const fallback = {
    lat: null,
    lon: null,
    speed_kmh: null,
    heading_deg: null,
    is_in_coverage: undefined,
    detections: [],
    frame_width: null,
    frame_height: null
  };
  if (!Array.isArray(points) || points.length === 0) return fallback;

  const target = Number.isFinite(timeSec) ? Math.max(0, timeSec) : 0;
  // Binary search the neighboring telemetry samples; avoids scanning every
  // decoded frame on every playback update for long dashcam videos.
  let low = 0;
  let high = points.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if ((Number(points[mid]?.time_sec) || 0) <= target) low = mid + 1;
    else high = mid;
  }

  const leftIndex = Math.max(0, low - 1);
  const rightIndex = Math.min(points.length - 1, low);
  const left = points[leftIndex] || points[0];
  const right = points[rightIndex] || left;
  const t0 = Number(left.time_sec) || 0;
  const t1 = Number(right.time_sec) || t0;
  const ratio = t1 > t0 ? Math.max(0, Math.min(1, (target - t0) / (t1 - t0))) : 0;

  const readNumber = (value) => {
    if (value === null || value === undefined || value === '') return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const interpolateNumber = (key) => {
    const a = readNumber(left[key]);
    const b = readNumber(right[key]);
    if (a !== null && b !== null) return a + ((b - a) * ratio);
    if (a !== null) return a;
    if (b !== null) return b;
    return null;
  };

  const lat = interpolateNumber('lat');
  const lon = interpolateNumber('lon');
  const speedKmh = interpolateNumber('speed_kmh');
  const headingA = readNumber(left.heading_deg);
  const headingB = readNumber(right.heading_deg);
  let heading = null;
  if (headingA !== null && headingB !== null) {
    // Interpolate along the short side of the compass (e.g. 359° -> 1°).
    const delta = ((headingB - headingA + 540) % 360) - 180;
    heading = ((headingA + (delta * ratio)) % 360 + 360) % 360;
  } else if (headingA !== null) heading = headingA;
  else if (headingB !== null) heading = headingB;

  // Smooth detections between adjacent analyzed frames and briefly bridge a single
  // missed sample. This keeps boxes aligned to a moving pothole without leaving
  // stale outlines visible long after the object has disappeared.
  const detections = interpolateDetectionBoxes(left, right, target, t0, t1, 0.45);

  const coveragePoint = ratio < 0.5 ? left : right;
  return {
    lat,
    lon,
    speed_kmh: speedKmh,
    heading_deg: heading,
    is_in_coverage: coveragePoint.is_in_coverage,
    frame_width: Number(coveragePoint.frame_width) || Number(left.frame_width) || Number(right.frame_width) || null,
    frame_height: Number(coveragePoint.frame_height) || Number(left.frame_height) || Number(right.frame_height) || null,
    detections
  };
}

export default function VideoPlayerHUD({ 
  videoUrl, 
  telemetry = [], 
  hazards = [], 
  currentTime = 0, 
  onTimeUpdate, 
  onSelectHazard,
  playbackWarning = null,
  onOpenUpload,
  isSynthetic = false,
  sourceName = 'Dashcam footage',
  liveInferenceEnabled = false,
  runId = null,
  onLiveInference = null,
  analysisStatus = null,
  analysisProgress = null,
  analysisMessage = null
}) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [activeAlert, setActiveAlert] = useState(null);
  const [playbackError, setPlaybackError] = useState(null);
  const [liveFrameResult, setLiveFrameResult] = useState(null);
  const [liveStatus, setLiveStatus] = useState('STANDBY');
  const [lastInferenceMs, setLastInferenceMs] = useState(null);
  const inferenceInFlightRef = useRef(false);
  const inferenceRequestIdRef = useRef(0);
  const lastInferenceTimeRef = useRef(-1);
  const pendingForcedInferenceRef = useRef(false);
  const activeVideoUrlRef = useRef(videoUrl);
  const inferenceCanvasRef = useRef(null);

  // Reset the player whenever a new run/video is selected.
  useEffect(() => {
    activeVideoUrlRef.current = videoUrl;
    // Invalidate any response from a previous clip so it cannot clear the
    // in-flight flag or paint old boxes over the newly selected video.
    inferenceRequestIdRef.current += 1;
    inferenceInFlightRef.current = false;
    pendingForcedInferenceRef.current = false;
    lastInferenceTimeRef.current = -1;
    setIsPlaying(false);
    setDuration(0);
    setPlaybackError(null);
    setLiveFrameResult(null);
    setLastInferenceMs(null);
    setLiveStatus(liveInferenceEnabled ? 'LIVE AI READY' : (isSynthetic ? 'DEMO / SAVED ANALYSIS' : 'SAVED FRAME ANALYSIS'));
  }, [videoUrl, runId]);

  // Processing can finish while the user keeps watching the same video. Change
  // the status without resetting playback or discarding the video element state.
  useEffect(() => {
    setLiveStatus(liveInferenceEnabled ? 'LIVE AI READY' : (isSynthetic ? 'DEMO / SAVED ANALYSIS' : 'SAVED FRAME ANALYSIS'));
  }, [liveInferenceEnabled, isSynthetic]);

  // Sync external seek (e.g. from clicking a hazard in the map or list).
  // Only seek after metadata is available to avoid invalid/NaN assignments.
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !Number.isFinite(currentTime) || video.readyState < 1) return;
    if (Math.abs(video.currentTime - currentTime) > 0.4) {
      try {
        video.currentTime = Math.max(0, duration > 0 ? Math.min(currentTime, duration) : currentTime);
        if (liveInferenceEnabled && video.paused) {
          requestLiveInference(true);
        }
      } catch (error) {
        console.warn('Video seek was deferred until media metadata is available.', error);
      }
    }
  }, [currentTime, duration, videoUrl, liveInferenceEnabled]);

  // Interpolate vehicle values at the precise playback timestamp; detections
  // remain tied to the latest sampled inference frame.
  const currentTelemetry = interpolateTelemetryAtTime(telemetry, currentTime);

  // Find hazards nearby in time (< 1.5s window) to trigger HUD warning
  useEffect(() => {
    const nearby = hazards.find(
      (h) => Math.abs(h.timestamp_sec - currentTime) < 1.2
    );
    if (nearby) {
      setActiveAlert(nearby);
    } else {
      setActiveAlert(null);
    }
  }, [currentTime, hazards]);

  // Draw genuine detector boxes or segmentation polygons over the active frame.
  // Polygon coordinates are source-frame pixels and are transformed through the
  // same letterbox/object-contain mapping as the video itself.
  useEffect(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const savedDetections = currentTelemetry.detections || [];
    const liveTimestamp = Number(liveFrameResult?.timestamp_sec);
    const liveFrameIsRecent = Number.isFinite(liveTimestamp) && Math.abs(currentTime - liveTimestamp) <= 1.25;
    const liveDetections = Array.isArray(liveFrameResult?.detections) ? liveFrameResult.detections : [];
    const useLiveDetections = Boolean(liveInferenceEnabled && liveFrameIsRecent && liveDetections.length > 0);
    const detections = useLiveDetections ? liveDetections : savedDetections;
    if (detections.length === 0) return;

    const videoWidth = video.videoWidth || 1280;
    const videoHeight = video.videoHeight || 720;
    const boxSourceWidth = useLiveDetections
      ? (Number(liveFrameResult?.frame_width) || videoWidth)
      : (Number(currentTelemetry.frame_width) || videoWidth);
    const boxSourceHeight = useLiveDetections
      ? (Number(liveFrameResult?.frame_height) || videoHeight)
      : (Number(currentTelemetry.frame_height) || videoHeight);
    const sourceScaleX = videoWidth / boxSourceWidth;
    const sourceScaleY = videoHeight / boxSourceHeight;
    const fitScale = Math.min(canvas.width / videoWidth, canvas.height / videoHeight);
    const offsetX = (canvas.width - (videoWidth * fitScale)) / 2;
    const offsetY = (canvas.height - (videoHeight * fitScale)) / 2;
    const transformPoint = (point) => ({
      x: (Number(point[0]) * sourceScaleX * fitScale) + offsetX,
      y: (Number(point[1]) * sourceScaleY * fitScale) + offsetY,
    });

    detections.forEach((det) => {
      const polygon = Array.isArray(det.polygon) ? det.polygon : null;
      const validPolygon = Boolean((det.has_mask === true || det.has_mask === 1 || String(det.has_mask).toLowerCase() === 'true')
        && polygon && polygon.length >= 3
        && polygon.every((point) => Array.isArray(point) && point.length >= 2
          && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1]))));
      let bbox = Array.isArray(det.bbox) && det.bbox.length === 4 ? det.bbox.map(Number) : null;
      if ((!bbox || !bbox.every(Number.isFinite) || bbox[2] <= bbox[0] || bbox[3] <= bbox[1]) && validPolygon) {
        const xs = polygon.map((point) => Number(point[0]));
        const ys = polygon.map((point) => Number(point[1]));
        bbox = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
      }
      if (!bbox || !bbox.every(Number.isFinite) || bbox[2] <= bbox[0] || bbox[3] <= bbox[1]) return;
      const [rawX1, rawY1, rawX2, rawY2] = bbox;
      const x1 = rawX1 * sourceScaleX;
      const y1 = rawY1 * sourceScaleY;
      const x2 = rawX2 * sourceScaleX;
      const y2 = rawY2 * sourceScaleY;
      const bx = (x1 * fitScale) + offsetX;
      const by = (y1 * fitScale) + offsetY;
      const bw = (x2 - x1) * fitScale;
      const bh = (y2 - y1) * fitScale;
      const isHeuristic = det.verification === 'provisional_heuristic'
        || det.source === 'cv_surface_analyzer'
        || det.type === 'possible_road_anomaly';
      const isGenuinePothole = !isHeuristic && (
        String(det.class_code || '').toUpperCase() === 'D40'
        || det.source === 'pothole_segmentation_model'
        || (det.type === 'pothole_damage' && (det.source === 'rdd2022_road_damage_model' || det.verification === 'model_inferred_unverified'))
      );
      const isRoadCrack = !isHeuristic && (
        ['D00', 'D10', 'D20'].includes(String(det.class_code || '').toUpperCase())
        || det.type === 'road_crack'
      );

      let color = '#3b82f6';
      if (isHeuristic) {
        color = '#94a3b8'; // Neutral slate grey: heuristics are not confirmed potholes
      } else if (isGenuinePothole) {
        color = '#dc2626'; // Red outline for genuine model D40 pothole
      } else if (isRoadCrack) {
        color = '#ea580c'; // Orange for road crack
      } else if (det.type === 'fallen_tree_debris' || det.type === 'powerline_hazard') {
        color = '#ef4444';
      } else if (det.type === 'road_flooding' || det.type === 'waterlogging') {
        color = '#0ea5e9';
      } else if (det.type === 'structural_blockage') {
        color = '#a855f7';
      }

      let labelX = bx;
      let labelY = by;

      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = Math.max(2, canvas.width / 520);
      ctx.setLineDash([]);
      if (validPolygon) {
        const transformed = polygon.map(transformPoint);
        labelX = Math.min(...transformed.map((point) => point.x));
        labelY = Math.min(...transformed.map((point) => point.y));
        ctx.beginPath();
        ctx.moveTo(transformed[0].x, transformed[0].y);
        for (let index = 1; index < transformed.length; index += 1) {
          ctx.lineTo(transformed[index].x, transformed[index].y);
        }
        ctx.closePath();
        ctx.fillStyle = isGenuinePothole ? 'rgba(220, 38, 38, 0.16)' : isHeuristic ? 'rgba(148, 163, 184, 0.14)' : `${color}22`;
        ctx.fill();
        ctx.stroke();
      } else {
        ctx.strokeRect(bx, by, bw, bh);
      }
      ctx.restore();

      const confidence = Number(det.conf ?? det.confidence);
      const confidenceText = Number.isFinite(confidence) ? ` ${confidence.toFixed(2)}` : '';
      let labelText;
      if (isHeuristic) {
        labelText = `POSSIBLE ROAD ANOMALY${confidenceText}`;
      } else if (isGenuinePothole) {
        labelText = `POTHOLE${confidenceText}`;
      } else if (isRoadCrack) {
        labelText = `ROAD CRACK${confidenceText}`;
      } else {
        labelText = `${String(det.label || det.type || 'ROAD HAZARD').toUpperCase()}${confidenceText}`;
      }

      ctx.save();
      ctx.font = 'bold 12px "JetBrains Mono", monospace';
      const textWidth = ctx.measureText(labelText).width;
      const labelTop = Math.max(0, labelY - 22);
      const labelLeft = Math.max(0, Math.min(canvas.width - textWidth - 12, labelX));
      ctx.fillStyle = color;
      ctx.fillRect(labelLeft, labelTop, textWidth + 12, 22);
      ctx.fillStyle = '#ffffff';
      ctx.fillText(labelText, labelLeft + 6, Math.max(16, labelTop + 15));
      ctx.restore();
    });
  }, [currentTelemetry, currentTime, liveInferenceEnabled, liveFrameResult, analysisStatus]);

  const togglePlay = async () => {
    const video = videoRef.current;
    if (!video || !videoUrl) {
      setPlaybackError('No video is available for this run. Upload a video or select a demo scenario.');
      return;
    }
    if (!video.paused) {
      video.pause();
      if (liveInferenceEnabled) {
        requestLiveInference(true);
      }
      return;
    }
    try {
      setPlaybackError(null);
      await video.play();
      // Playback state is synchronized by the media element's onPlay event.
    } catch (error) {
      setIsPlaying(false);
      const message = error?.name === 'NotSupportedError'
        ? 'This video uses a codec the browser cannot play. Use an H.264 MP4, or enable FFmpeg playback conversion in CivicRoute AD.'
        : error?.name === 'NotAllowedError'
          ? 'The browser blocked playback. Click Play once more to start the video.'
          : `Video playback could not start: ${error?.message || 'unknown media error'}`;
      setPlaybackError(message);
      console.error('CivicRoute AD video playback failed:', error);
    }
  };

  const requestLiveInference = async (force = false) => {
    const video = videoRef.current;
    if (!liveInferenceEnabled || !videoUrl || !video || video.readyState < 2) return;
    if (inferenceInFlightRef.current) {
      // A seek should still be inferred once the current slow CPU inference returns.
      if (force) pendingForcedInferenceRef.current = true;
      return;
    }
    const requestedAt = Number.isFinite(video.currentTime) ? video.currentTime : 0;
    if (!force && requestedAt - lastInferenceTimeRef.current < 0.45) return;

    // Sample the actual displayed frame and send it to the local FastAPI model.
    // The client caps frame size to 960px wide to control CPU and network cost.
    inferenceInFlightRef.current = true;
    const requestId = ++inferenceRequestIdRef.current;
    lastInferenceTimeRef.current = requestedAt;
    const requestVideoUrl = videoUrl;
    setLiveStatus('AI INFERENCE…');
    try {
      const maxWidth = 960;
      const width = Math.min(video.videoWidth || 960, maxWidth);
      const height = Math.max(1, Math.round(width * ((video.videoHeight || 540) / (video.videoWidth || 960))));
      let sampleCanvas = inferenceCanvasRef.current;
      if (!sampleCanvas) {
        sampleCanvas = document.createElement('canvas');
        inferenceCanvasRef.current = sampleCanvas;
      }
      sampleCanvas.width = width;
      sampleCanvas.height = height;
      const context = sampleCanvas.getContext('2d', { alpha: false });
      if (!context) throw new Error('Canvas is unavailable for video-frame sampling.');
      context.drawImage(video, 0, 0, width, height);
      const frameBlob = await new Promise((resolve) => sampleCanvas.toBlob(resolve, 'image/jpeg', 0.72));
      if (!frameBlob) throw new Error('Could not encode the current video frame.');

      const result = await detectVideoFrame(frameBlob, requestedAt, runId);
      const activeVideo = videoRef.current;
      if (requestId !== inferenceRequestIdRef.current
          || activeVideoUrlRef.current !== requestVideoUrl || !activeVideo) return;
      // A CPU detector may take longer than the browser's playback cadence.
      // Keep a valid result during normal playback instead of throwing it away
      // (which made the road-scan overlay appear permanently blank). If the user
      // explicitly paused/seeks to a different timestamp while the request was
      // running, discard that stale result so it cannot land on the wrong frame.
      const playbackDrift = Math.abs((activeVideo.currentTime || 0) - requestedAt);
      if (activeVideo.paused && playbackDrift > 1.25) {
        setLiveStatus('SEEKED · RESCAN CURRENT FRAME');
        return;
      }

      const frameResult = {
        detections: Array.isArray(result.detections) ? result.detections : [],
        frame_width: result.frame_width || width,
        frame_height: result.frame_height || height,
        timestamp_sec: result.timestamp_sec ?? requestedAt,
        count: result.count || 0,
        engine: result.engine || 'Local AI',
        model_status: result.model_status || null,
        warning: result.warning || null,
      };
      setLiveFrameResult(frameResult);
      if (typeof onLiveInference === 'function') onLiveInference(result);
      setLastInferenceMs(Number.isFinite(result.inference_ms) ? result.inference_ms : null);
      const detectedItems = Array.isArray(result.detections) ? result.detections : [];
      const potholeCount = detectedItems.filter((item) =>
        item.class_code === 'D40' || /pothole|road cavity/i.test(String(item.label || ''))
      ).length;
      const roadModelReady = Boolean(result.model_status?.road_damage_model_loaded);
      const resultStatus = result.count > 0
        ? `LIVE • ${result.count} BOX${result.count === 1 ? '' : 'ES'}${potholeCount ? ` · ${potholeCount} POTHOLE${potholeCount === 1 ? '' : 'S'}` : ''}`
        : roadModelReady
          ? 'LIVE • NO ROAD DAMAGE IN THIS FRAME'
          : 'LIVE • FALLBACK MODEL · POTHOLE RECALL LIMITED';
      setLiveStatus(playbackDrift > 0.8 && !activeVideo.paused
        ? `${resultStatus} · ${playbackDrift.toFixed(1)}s FRAME LAG`
        : resultStatus);
    } catch (error) {
      console.warn('CivicRouteAD live frame inference failed:', error);
      setLiveStatus(`AI REQUEST FAILED · ${error?.message || 'CHECK BACKEND'}`);
    } finally {
      if (requestId === inferenceRequestIdRef.current) {
        inferenceInFlightRef.current = false;
        const activeVideo = videoRef.current;
        const forcedSeekWaiting = pendingForcedInferenceRef.current;
        pendingForcedInferenceRef.current = false;
        if (liveInferenceEnabled && activeVideo && forcedSeekWaiting) {
          window.setTimeout(() => requestLiveInference(true), 0);
        } else if (liveInferenceEnabled && activeVideo && !activeVideo.paused
            && (activeVideo.currentTime - lastInferenceTimeRef.current) >= 0.45) {
          // A timer ensures a fresh frame is queued even if this response arrived
          // between the browser's timeupdate events.
          window.setTimeout(() => requestLiveInference(false), 0);
        }
      }
    }
  };

  const handleTimeUpdate = () => {
    const video = videoRef.current;
    if (video && Number.isFinite(video.currentTime)) {
      onTimeUpdate(video.currentTime);
      if (!video.paused) requestLiveInference(false);
    }
  };

  const handleLoadedMetadata = () => {
    const video = videoRef.current;
    if (!video) return;
    const nextDuration = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : 0;
    setDuration(nextDuration);
    setPlaybackError(null);
    if (Number.isFinite(video.currentTime)) onTimeUpdate(video.currentTime);
    if (liveInferenceEnabled) requestLiveInference(true);
  };

  const handleMediaError = () => {
    const mediaError = videoRef.current?.error;
    const code = mediaError?.code;
    const reason = code === 2 ? 'A network error interrupted video loading.'
      : code === 3 ? 'The browser could not decode the video.'
      : code === 4 ? 'The browser does not support this video source or codec.'
      : 'The video file could not be loaded.';
    setIsPlaying(false);
    setDuration(0);
    setPlaybackError(reason);
  };

  const handleSeek = (e) => {
    if (!videoRef.current || !Number.isFinite(duration) || duration <= 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const pos = (e.clientX - rect.left) / rect.width;
    const newTime = pos * duration;
    if (videoRef.current) {
      videoRef.current.currentTime = newTime;
      onTimeUpdate(newTime);
      if (liveInferenceEnabled) {
        requestLiveInference(true);
      }
    }
  };

  const cycleSpeed = () => {
    const nextRate = playbackRate === 1 ? 2 : playbackRate === 2 ? 0.5 : 1;
    setPlaybackRate(nextRate);
    if (videoRef.current) {
      videoRef.current.playbackRate = nextRate;
    }
  };

  const formatTime = (sec) => {
    if (!Number.isFinite(sec) || sec < 0) return '00:00.0';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    const ms = Math.floor((sec % 1) * 10);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}.${ms}`;
  };

  const formatLatLon = (lat, lon, isInCoverage) => {
    if (isInCoverage === false) return 'GPS OUTSIDE TRACK';
    if (typeof lat !== 'number' || typeof lon !== 'number' || !Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      return 'GPS UNAVAILABLE';
    }
    const latStr = `${Math.abs(lat).toFixed(6)}° ${lat >= 0 ? 'N' : 'S'}`;
    const lonStr = `${Math.abs(lon).toFixed(6)}° ${lon >= 0 ? 'E' : 'W'}`;
    return `${latStr}, ${lonStr}`;
  };

  return (
    <div className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden shadow-2xl flex flex-col">
      {/* Source control stays inside the Analysis Lab video panel. Demo footage is
          explicitly marked as a placeholder; processing an upload replaces it. */}
      <div className="flex items-center justify-between gap-3 px-3 py-2.5 bg-slate-950/90 border-b border-slate-800">
        <div className="min-w-0 flex flex-col gap-0.5">
          <div className="flex flex-wrap items-center gap-2 text-[10px] font-bold tracking-wider">
            <span className="text-slate-400">VIDEO SOURCE</span>
            <span className={`rounded px-1.5 py-0.5 border ${isSynthetic ? 'text-amber-300 border-amber-500/40 bg-amber-500/10' : 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10'}`}>
              {isSynthetic ? 'DEMO PLACEHOLDER' : 'UPLOADED FOOTAGE'}
            </span>
          </div>
          <span className="text-[11px] text-slate-400 truncate" title={sourceName}>{sourceName}</span>
        </div>
        <button
          type="button"
          onClick={onOpenUpload}
          disabled={!onOpenUpload}
          className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-600/15 px-2.5 py-2 text-[10px] font-bold text-blue-200 hover:bg-blue-600/30 hover:text-white transition-colors disabled:opacity-50"
          title="Upload a dashcam MP4 and matching GPX/CSV GPS track"
        >
          <UploadCloud className="w-3.5 h-3.5" />
          {isSynthetic ? 'UPLOAD MP4 + GPS' : 'REPLACE FOOTAGE'}
        </button>
      </div>

      {/* Video Container with Overlays */}
      <div className="relative aspect-video bg-black flex items-center justify-center overflow-hidden group">
        
        {/* HTML5 Video */}
        <video
          key={videoUrl || 'no-video'}
          ref={videoRef}
          src={videoUrl || undefined}
          className="w-full h-full object-contain"
          onTimeUpdate={handleTimeUpdate}
          onSeeked={() => { if (liveInferenceEnabled) requestLiveInference(true); }}
          onLoadedMetadata={handleLoadedMetadata}
          onLoadedData={() => { if (liveInferenceEnabled) requestLiveInference(true); }}
          onCanPlay={() => {
            setPlaybackError(null);
            if (liveInferenceEnabled) requestLiveInference(true);
          }}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onEnded={() => setIsPlaying(false)}
          onError={handleMediaError}
          playsInline
          preload="metadata"
        />

        {(playbackError || playbackWarning) && (
          <div className="absolute left-4 right-4 bottom-4 z-30 rounded-lg border border-amber-500/40 bg-slate-950/95 px-3 py-2 text-xs text-amber-200 shadow-xl">
            <div className="font-bold mb-1">{playbackError ? 'VIDEO PLAYBACK ISSUE' : 'PLAYBACK NOTE'}</div>
            <div>{playbackError || playbackWarning}</div>
          </div>
        )}

        {!videoUrl && !playbackError && (
          <div className="absolute inset-x-8 bottom-6 z-20 text-center text-xs text-slate-400">No video source is linked to this run.</div>
        )}


        {/* AI Bounding Box Canvas Overlay */}
        <canvas
          ref={canvasRef}
          width={1280}
          height={720}
          className="absolute inset-0 w-full h-full pointer-events-none z-10"
        />

        {/* Dashcam HUD Telemetry Overlay (Top Corners) */}
        <div className="absolute top-3 left-3 z-20 flex flex-col gap-1.5 pointer-events-none">
          <div className="flex items-center gap-2 bg-black/70 backdrop-blur-md px-2.5 py-1 rounded border border-slate-700/60 font-mono text-xs text-cyan-300 shadow-md">
            <span className={`inline-block h-2 w-2 rounded-full ${analysisStatus === 'processing' ? 'bg-amber-400' : liveInferenceEnabled ? 'bg-red-400' : 'bg-cyan-400'}`} aria-hidden="true" />
            <span>
              {analysisStatus === 'processing'
                ? `FULL VIDEO ANALYSIS ${Number.isFinite(Number(analysisProgress)) ? `${Math.round(Number(analysisProgress))}%` : 'RUNNING'}`
                : analysisStatus === 'failed'
                  ? 'VIDEO ANALYSIS FAILED'
                  : analysisStatus === 'completed' && !isSynthetic
                    ? 'ANALYSIS COMPLETE // SAVED BOXES READY'
                  : liveInferenceEnabled
                    ? 'LIVE VIDEO // HAZARD DETECTION'
                    : (isSynthetic ? 'DEMO PLACEHOLDER // SAVED ANALYSIS' : 'UPLOADED VIDEO // SAVED DETECTIONS')}
            </span>
          </div>
          {analysisStatus === 'processing' && analysisMessage && (
            <div className="max-w-[85%] bg-black/75 px-2.5 py-1 rounded border border-amber-500/30 font-mono text-[10px] text-amber-200 shadow-md">
              {analysisMessage}
            </div>
          )}
          <div className="bg-black/70 backdrop-blur-md px-2.5 py-1.5 rounded border border-slate-700/60 font-mono text-[11px] text-slate-300 shadow-md flex flex-col">
            <span className="text-slate-400">GPS COORDINATES</span>
            <span className="text-white font-bold">
              {formatLatLon(currentTelemetry.lat, currentTelemetry.lon, currentTelemetry.is_in_coverage)}
            </span>
          </div>
        </div>

        {/* Top Right: Speed & Compass Telemetry */}
        <div className="absolute top-3 right-3 z-20 flex items-center gap-2 pointer-events-none">
          <div className="flex items-center gap-1.5 bg-black/70 backdrop-blur-md px-3 py-1.5 rounded border border-slate-700/60 font-mono text-xs shadow-md">
            <Compass 
              className="w-4 h-4 text-emerald-400 transition-transform duration-300"
              style={{ transform: `rotate(${Number.isFinite(currentTelemetry.heading_deg) ? currentTelemetry.heading_deg : 0}deg)` }}
            />
            <span className="text-white font-bold">{Number.isFinite(currentTelemetry.heading_deg) ? `${Math.round(currentTelemetry.heading_deg)}°` : '—'}</span>
          </div>

          <div className="flex items-center gap-1.5 bg-black/70 backdrop-blur-md px-3 py-1.5 rounded border border-slate-700/60 font-mono text-xs shadow-md">
            <Gauge className="w-4 h-4 text-amber-400" />
            <span className="text-white font-bold">{Number.isFinite(currentTelemetry.speed_kmh) ? currentTelemetry.speed_kmh.toFixed(1) : '—'}</span>
            <span className="text-[10px] text-slate-400">KM/H</span>
          </div>
        </div>

        {/* Active Hazard Warning Banner in HUD */}
        {activeAlert && (
          <div 
            onClick={() => onSelectHazard(activeAlert)}
            className="absolute bottom-16 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2.5 bg-red-600/90 text-white font-bold text-xs uppercase px-4 py-2 rounded-lg border border-red-400 shadow-2xl backdrop-blur-md cursor-pointer animate-bounce hover:scale-105 transition-transform"
          >
            <AlertOctagon className="w-4 h-4 animate-pulse" />
            <span>
              HAZARD DETECTED: {activeAlert.id} - {activeAlert.type.replace(/_/g, ' ')} ({activeAlert.forward_distance_m}m)
            </span>
          </div>
        )}

        {/* Central Play Button Overlay when paused */}
        {!isPlaying && (
          <button
            onClick={togglePlay}
            className="absolute inset-0 flex items-center justify-center bg-black/30 group-hover:bg-black/40 transition-colors z-20"
          >
            <div className="w-16 h-16 rounded-full bg-blue-600/90 text-white flex items-center justify-center shadow-xl hover:scale-110 active:scale-95 transition-all">
              <Play className="w-8 h-8 translate-x-0.5 fill-current" />
            </div>
          </button>
        )}
      </div>

      {/* Video Control Bar & Scrubber */}
      <div className="p-3 bg-slate-900 border-t border-slate-800 flex flex-col gap-2">
        {/* Scrubber with Hazard Markers */}
        <div 
          onClick={handleSeek}
          className="relative h-2 bg-slate-800 rounded-full cursor-pointer hover:h-2.5 transition-all overflow-visible group/bar"
        >
          {/* Progress fill */}
          <div 
            className="absolute left-0 top-0 bottom-0 bg-gradient-to-r from-blue-500 to-cyan-400 rounded-full"
            style={{ width: `${duration ? Math.max(0, Math.min(100, (currentTime / duration) * 100)) : 0}%` }}
          />

          {/* Hazard markers on timeline */}
          {hazards.map((h) => {
            const posPercent = duration ? Math.max(0, Math.min(100, (h.timestamp_sec / duration) * 100)) : 0;
            const isCrit = h.severity === 'Critical';
            return (
              <div
                key={h.id}
                title={`${h.id}: ${h.type} (${h.severity})`}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectHazard(h);
                }}
                className={`absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full border border-slate-900 transition-transform hover:scale-150 ${
                  isCrit ? 'bg-red-500' : 'bg-amber-400'
                }`}
                style={{ left: `${posPercent}%` }}
              />
            );
          })}
        </div>

        {/* Bottom Playback Controls */}
        <div className="flex items-center justify-between text-xs text-slate-300">
          <div className="flex items-center gap-3">
            <button
              onClick={togglePlay}
              className="p-1.5 hover:bg-slate-800 rounded text-slate-200 hover:text-white transition-colors"
            >
              {isPlaying ? <Pause className="w-4 h-4 fill-current" /> : <Play className="w-4 h-4 fill-current" />}
            </button>

            <button
              onClick={() => {
                if (videoRef.current && duration > 0) {
                  videoRef.current.currentTime = 0;
                  onTimeUpdate(0);
                }
              }}
              className="p-1.5 hover:bg-slate-800 rounded text-slate-400 hover:text-white transition-colors"
              title="Restart"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>

            {/* Time readout */}
            <span className="font-mono text-[11px] text-slate-400">
              <span className="text-cyan-400 font-bold">{formatTime(currentTime)}</span> / {formatTime(duration)}
            </span>
          </div>

          <div className="flex items-center gap-2">
            {/* Speed toggle */}
            <button
              onClick={cycleSpeed}
              className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 font-mono text-[11px] text-slate-300"
            >
              {playbackRate}x
            </button>

            <div className="text-[11px] font-mono text-slate-400 flex items-center gap-1">
              <span className={`w-2 h-2 rounded-full inline-block ${playbackError ? 'bg-amber-500' : 'bg-emerald-500'}`}></span>
              <span>{playbackError ? 'VIDEO ERROR' : liveInferenceEnabled ? `${liveStatus}${lastInferenceMs !== null ? ` · ${Math.round(lastInferenceMs)}ms` : ''}` : 'DEMO / PRECOMPUTED'}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
