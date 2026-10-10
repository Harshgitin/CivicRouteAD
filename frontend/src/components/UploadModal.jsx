import React, { useState } from 'react';
import { 
  X, 
  UploadCloud, 
  Video, 
  Compass, 
  CheckCircle2, 
  AlertCircle, 
  Loader2,
  Clock,
  FileCheck,
  HelpCircle
} from 'lucide-react';
import { processUpload } from '../utils/api';

export default function UploadModal({ isOpen, onClose, onUploadSuccess }) {
  const [videoFile, setVideoFile] = useState(null);
  const [gpsFile, setGpsFile] = useState(null);
  const [timeOffsetSec, setTimeOffsetSec] = useState(0.0);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState(null);

  if (!isOpen) return null;

  const handleVideoSelect = (file) => {
    setError(null);
    if (!file) return;
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['mp4', 'webm', 'mov', 'avi', 'mkv'].includes(ext)) {
      setError(`Unsupported video format (.${ext}). Please select an MP4, WebM, or MOV video.`);
      return;
    }
    if (file.size > 500 * 1024 * 1024) {
      setError('Video file exceeds maximum size limit (500MB).');
      return;
    }
    setVideoFile(file);
  };

  const handleGpsSelect = (file) => {
    setError(null);
    if (!file) return;
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['gpx', 'csv'].includes(ext)) {
      setError(`Unsupported GPS format (.${ext}). Please select a standard GPX (.gpx) or CSV (.csv) trajectory log.`);
      return;
    }
    setGpsFile(file);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!videoFile) {
      setError('Missing video file: Please select a dashcam or phone video (.mp4 or .webm).');
      return;
    }
    setIsProcessing(true);
    setError(null);

    try {
      const result = await processUpload(videoFile, gpsFile, timeOffsetSec);
      setIsProcessing(false);
      onUploadSuccess(result);
      onClose();
    } catch (err) {
      setIsProcessing(false);
      setError(err.message || 'Error preparing the uploaded video for analysis.');
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-[#111827] border border-slate-700 rounded-2xl max-w-lg w-full overflow-hidden shadow-2xl animate-in fade-in zoom-in-95 duration-200">
        
        {/* Modal Header */}
        <div className="bg-slate-900 border-b border-slate-800 p-4 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-blue-600/20 text-blue-400 rounded-lg">
              <UploadCloud className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white">Upload Dashcam Footage</h3>
              <p className="text-[11px] text-slate-400">Live on-video detection starts with the selected footage; GPS enables GIS mapping.</p>
            </div>
          </div>
          <button 
            onClick={onClose}
            disabled={isProcessing}
            className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-5 flex flex-col gap-4">
          
          {error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-xs text-red-400 flex items-start gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span className="leading-relaxed">{error}</span>
            </div>
          )}

          {/* Validation Status Indicator */}
          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3 flex flex-col gap-2">
            <span className="text-[11px] font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
              <FileCheck className="w-3.5 h-3.5 text-cyan-400" />
              Pipeline Input Checklist
            </span>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className={`p-2 rounded-lg border flex items-center gap-2 ${
                videoFile 
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' 
                  : 'bg-slate-800/40 border-slate-700 text-slate-400'
              }`}>
                {videoFile ? <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" /> : <div className="w-4 h-4 rounded-full border border-slate-600 shrink-0" />}
                <span className="truncate">{videoFile ? videoFile.name : '1. Select Video'}</span>
              </div>

              <div className={`p-2 rounded-lg border flex items-center gap-2 ${
                gpsFile 
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' 
                  : 'bg-slate-800/40 border-slate-700 text-slate-400'
              }`}>
                {gpsFile ? <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" /> : <div className="w-4 h-4 rounded-full border border-slate-600 shrink-0" />}
                <span className="truncate">{gpsFile ? gpsFile.name : '2. GPS (optional for live detection)'}</span>
              </div>
            </div>
          </div>

          {/* 1. Dashcam Video File Input */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-slate-300 flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <Video className="w-4 h-4 text-cyan-400" />
                Dashcam Video Feed (.mp4, .webm)
              </span>
              <span className="text-[10px] text-slate-500 font-normal">Max 500MB</span>
            </label>
            <label className={`border-2 border-dashed rounded-xl p-3.5 flex flex-col items-center justify-center cursor-pointer transition-colors text-center ${
              videoFile ? 'border-cyan-500/50 bg-cyan-950/20' : 'border-slate-700 hover:border-blue-500/80 bg-slate-900/50 hover:bg-slate-900'
            }`}>
              <input
                type="file"
                accept="video/mp4,video/webm,video/quicktime,video/x-matroska"
                onChange={(e) => handleVideoSelect(e.target.files[0])}
                disabled={isProcessing}
                className="hidden"
              />
              {videoFile ? (
                <div className="flex items-center gap-2 text-xs font-mono text-cyan-300">
                  <Video className="w-4 h-4 text-cyan-400" />
                  <span className="font-semibold truncate max-w-[260px]">{videoFile.name}</span>
                  <span className="text-slate-500">({(videoFile.size / (1024 * 1024)).toFixed(1)}MB)</span>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-1 text-slate-400">
                  <span className="text-xs font-medium text-slate-200">Click to choose video file</span>
                  <span className="text-[11px] text-slate-500">Forward-facing road dashcam / phone recording</span>
                </div>
              )}
            </label>
          </div>

          {/* 2. GPS Trajectory Log File Input */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-slate-300 flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <Compass className="w-4 h-4 text-emerald-400" />
                Synchronized GPS Trajectory Data (.gpx, .csv)
              </span>
              <span className="text-[10px] text-amber-400 font-semibold">Optional • required for GIS</span>
            </label>
            <label className={`border-2 border-dashed rounded-xl p-3.5 flex flex-col items-center justify-center cursor-pointer transition-colors text-center ${
              gpsFile ? 'border-emerald-500/50 bg-emerald-950/20' : 'border-slate-700 hover:border-emerald-500/80 bg-slate-900/50 hover:bg-slate-900'
            }`}>
              <input
                type="file"
                accept=".gpx,.csv"
                onChange={(e) => handleGpsSelect(e.target.files[0])}
                disabled={isProcessing}
                className="hidden"
              />
              {gpsFile ? (
                <div className="flex items-center gap-2 text-xs font-mono text-emerald-300">
                  <Compass className="w-4 h-4 text-emerald-400" />
                  <span className="font-semibold truncate max-w-[260px]">{gpsFile.name}</span>
                  <span className="text-slate-500">({(gpsFile.size / 1024).toFixed(1)}KB)</span>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-1 text-slate-400">
                  <span className="text-xs font-medium text-slate-200">Click to choose GPS track file</span>
                  <span className="text-[11px] text-slate-500">Standard GPX 1.1 or CSV (time, lat, lon)</span>
                </div>
              )}
            </label>
          </div>

          {/* 3. Optional Clock Time Offset */}
          <div className="flex items-center justify-between bg-slate-900/50 border border-slate-800 rounded-xl px-3 py-2 text-xs">
            <div className="flex items-center gap-2 text-slate-300">
              <Clock className="w-4 h-4 text-indigo-400" />
              <div>
                <span className="font-semibold block text-[11px]">Time Offset (Video to GPS)</span>
                <span className="text-[10px] text-slate-500">Adjust if dashcam and GPS clocks differ</span>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <input
                type="number"
                step="0.1"
                value={timeOffsetSec}
                onChange={(e) => setTimeOffsetSec(parseFloat(e.target.value) || 0.0)}
                disabled={isProcessing}
                className="w-16 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-right text-xs text-white font-mono focus:outline-none focus:border-blue-500"
              />
              <span className="text-slate-500 text-[11px]">sec</span>
            </div>
          </div>

          {/* Lightweight feedback: the selected video appears as soon as playback prep ends;
              GPS-backed full GIS processing is performed in the background. */}
          {isProcessing && (
            <div className="bg-blue-950/40 border border-blue-500/40 rounded-xl p-3 flex items-start gap-2.5">
              <Loader2 className="w-4 h-4 animate-spin text-cyan-400 shrink-0 mt-0.5" />
              <div className="flex flex-col gap-1">
                <span className="text-xs font-bold text-cyan-300">Uploading & preparing video for playback…</span>
                <span className="text-[11px] text-slate-400 leading-relaxed">
                  Hazard outlines update over the selected clip as frames are analyzed. Full GPS-to-GIS analysis continues in the background.
                </span>
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex items-center justify-between pt-3 border-t border-slate-800">
            <span className="text-[11px] text-slate-500 italic">
              {!videoFile ? 'Select a video to begin' : !gpsFile ? 'Live AI video detection only • no GPS map coordinates' : 'Live AI + background GIS mapping ready'}
            </span>

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={onClose}
                disabled={isProcessing}
                className="px-4 py-2 text-xs font-medium text-slate-400 hover:text-white transition-colors"
              >
                Cancel
              </button>

              <button
                type="submit"
                disabled={isProcessing}
                className="flex items-center gap-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-bold px-5 py-2.5 rounded-xl shadow-lg shadow-blue-500/25 transition-all active:scale-95 disabled:opacity-50 cursor-pointer"
              >
                {isProcessing ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Processing Pipeline...</span>
                  </>
                ) : (
                  <>
                    <UploadCloud className="w-4 h-4" />
                    <span>{gpsFile ? 'Start Live AI + GIS' : 'Start Live Detection'}</span>
                  </>
                )}
              </button>
            </div>
          </div>

        </form>

      </div>
    </div>
  );
}
