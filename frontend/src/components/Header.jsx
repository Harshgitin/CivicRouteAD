import React from 'react';
import { 
  ShieldAlert, 
  MapPin, 
  UploadCloud, 
  Download, 
  FileText, 
  RefreshCw, 
  Layers, 
  CheckCircle2,
  Navigation,
  FileSpreadsheet
} from 'lucide-react';

export default function Header({ 
  scenarios, 
  selectedScenario, 
  onSelectScenario, 
  isLoading, 
  onOpenUpload, 
  onOpenReport,
  runData 
}) {
  const currentRunId = runData?.run_id;

  return (
    <header className="bg-[#0f172a] border-b border-slate-800 sticky top-0 z-40 px-4 py-3 shadow-xl backdrop-blur-md bg-opacity-95">
      <div className="max-w-[1920px] mx-auto flex flex-wrap items-center justify-between gap-4">
        
        {/* Brand & System Status */}
        <div className="flex items-center gap-3">
          <div className="relative flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-blue-600 via-indigo-600 to-cyan-500 shadow-lg shadow-blue-500/20 text-white font-bold">
            <ShieldAlert className="w-6 h-6" />
            <span className="absolute -top-1 -right-1 flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
            </span>
          </div>

          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-extrabold tracking-tight text-white flex items-center gap-1.5">
                CivicRoute<span className="text-cyan-400">AD</span>
              </h1>
              <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/30">
                Edge-to-GIS v1.0
              </span>
              {runData?.is_synthetic ? (
                <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/30 hidden md:inline-flex items-center gap-1">
                  🧪 Synthetic Test Fixture
                </span>
              ) : runData ? (
                <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-slate-700/60 text-slate-200 border border-slate-500/40 hidden md:inline-flex items-center gap-1">
                  User Upload · Unverified
                </span>
              ) : null}
            </div>
            <p className="text-xs text-slate-400 hidden sm:block">
              Automated Road Obstruction & Hazard Mapping from Street/Dashcam Video
            </p>
          </div>
        </div>

        {/* Central Controls: Scenario Switcher & Upload */}
        <div className="flex items-center gap-3 flex-wrap">
          {/* Scenario Select */}
          <div className="flex items-center gap-2 bg-slate-900/90 border border-slate-800 rounded-lg px-3 py-1.5 shadow-inner">
            <Layers className="w-4 h-4 text-blue-400 shrink-0" />
            <select
              value={selectedScenario}
              onChange={(e) => onSelectScenario(e.target.value)}
              disabled={isLoading}
              className="bg-transparent text-xs text-slate-200 font-medium focus:outline-none cursor-pointer max-w-[240px] truncate"
            >
              {scenarios.map((sc) => (
                <option key={sc.id} value={sc.id} className="bg-slate-900 text-slate-200">
                  {sc.title}
                </option>
              ))}
            </select>
          </div>

          {/* Upload Custom Data Button */}
          <button
            onClick={onOpenUpload}
            disabled={isLoading}
            className="flex items-center gap-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-md shadow-blue-600/20 transition-all active:scale-95 disabled:opacity-50"
          >
            <UploadCloud className="w-4 h-4" />
            <span>Upload MP4 + GPS</span>
          </button>
        </div>

        {/* Action & Export Tools */}
        <div className="flex items-center gap-2">
          {/* GeoJSON Export */}
          <a
            href={currentRunId ? `/api/geojson/${currentRunId}` : '#'}
            download={`civicroute_${currentRunId || 'export'}.geojson`}
            target="_blank"
            rel="noreferrer"
            className={`flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border transition-all ${
              currentRunId
                ? 'bg-slate-800/80 hover:bg-slate-700/80 text-cyan-300 border-cyan-500/30 hover:border-cyan-400'
                : 'opacity-40 pointer-events-none text-slate-500 border-slate-800'
            }`}
          >
            <Download className="w-3.5 h-3.5" />
            <span className="hidden md:inline">Export</span> GeoJSON
          </a>

          {/* CSV Export */}
          <a
            href={currentRunId ? `/api/export/csv/${currentRunId}` : '#'}
            download={`civicroute_${currentRunId || 'export'}.csv`}
            className={`flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border transition-all ${
              currentRunId
                ? 'bg-slate-800/80 hover:bg-slate-700/80 text-emerald-300 border-emerald-500/30 hover:border-emerald-400'
                : 'opacity-40 pointer-events-none text-slate-500 border-slate-800'
            }`}
          >
            <FileSpreadsheet className="w-3.5 h-3.5" />
            <span className="hidden md:inline">Export</span> CSV
          </a>

          {/* Municipal Work Order Report */}
          <button
            onClick={onOpenReport}
            disabled={!currentRunId}
            className={`flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border transition-all ${
              currentRunId
                ? 'bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border-amber-500/40 hover:border-amber-400'
                : 'opacity-40 pointer-events-none text-slate-500 border-slate-800'
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span className="hidden md:inline">Municipal</span> Report
          </button>
        </div>

      </div>
    </header>
  );
}
