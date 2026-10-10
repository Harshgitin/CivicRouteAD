import React from 'react';
import { 
  Activity, 
  Route, 
  Clock, 
  AlertOctagon, 
  CheckCircle, 
  BarChart3, 
  ShieldCheck, 
  Building2,
  TrendingDown
} from 'lucide-react';

export default function AnalyticsPanel({ runData }) {
  const meta = runData?.metadata || {};
  const hazards = runData?.hazards || [];

  const distanceKm = Number.isFinite(meta.total_distance_m) ? (meta.total_distance_m / 1000).toFixed(2) : '—';
  const durationSec = Number.isFinite(meta.duration_sec) ? meta.duration_sec.toFixed(1) : '—';
  const totalCount = hazards.length;

  const criticalCount = hazards.filter((h) => h.severity === 'Critical').length;
  const highCount = hazards.filter((h) => h.severity === 'High').length;
  const mediumCount = hazards.filter((h) => h.severity === 'Medium').length;
  const lowCount = hazards.filter((h) => h.severity === 'Low').length;

  // Road Health Score (starts at 100%, deducts points based on severity)
  const healthDeductions = (criticalCount * 25) + (highCount * 12) + (mediumCount * 5) + (lowCount * 2);
  const healthScore = Math.max(15, 100 - healthDeductions);

  const getHealthColor = (score) => {
    if (score >= 80) return 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10';
    if (score >= 50) return 'text-amber-400 border-amber-500/40 bg-amber-500/10';
    return 'text-red-400 border-red-500/40 bg-red-500/10';
  };

  return (
    <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 shadow-2xl flex flex-col gap-4">
      {/* Title */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-cyan-400" />
          <h3 className="text-xs font-bold text-white uppercase tracking-wider">
            Situational Awareness & Infrastructure Health
          </h3>
        </div>
        <div className="flex items-center gap-2">
          {runData?.is_synthetic ? (
            <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
              SYNTHETIC BENCHMARK FIXTURE
            </span>
          ) : runData ? (
            <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-slate-700/60 text-slate-200 border border-slate-500/40">
              USER UPLOADED · UNVERIFIED
            </span>
          ) : null}
          <span className="text-[10px] font-mono text-slate-400">
            Run: {runData?.run_id || 'ACTIVE'}
          </span>
        </div>
      </div>

      {runData?.is_synthetic ? (
        <div className="bg-amber-950/30 border border-amber-600/30 rounded-lg px-3 py-2 text-[11px] text-amber-300 flex items-center justify-between">
          <span>
            ℹ️ <strong>Test Fixture Notice:</strong> This scenario uses simulated dashcam footage and GPS logs designed for functional pipeline verification. The synthetic route is illustrative and is not map-matched road ground truth.
          </span>
        </div>
      ) : runData ? (
        <div className="bg-slate-900/70 border border-slate-700 rounded-lg px-3 py-2 text-[11px] text-slate-300">
          <strong>User-upload notice:</strong> These inputs have not been independently verified. AI detections and camera-projected locations are preliminary and should be reviewed before operational use.
        </div>
      ) : null}

      {/* 5 KPI Metric Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        
        {/* Distance */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-lg p-3 flex flex-col">
          <span className="text-[11px] font-medium text-slate-400 flex items-center gap-1.5 mb-1">
            <Route className="w-3.5 h-3.5 text-blue-400" />
            Survey Distance
          </span>
          <div className="flex items-baseline gap-1 mt-auto">
            <span className="text-xl font-extrabold text-white font-mono">{distanceKm}</span>
            <span className="text-xs text-slate-400 font-mono">KM</span>
          </div>
        </div>

        {/* Duration */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-lg p-3 flex flex-col">
          <span className="text-[11px] font-medium text-slate-400 flex items-center gap-1.5 mb-1">
            <Clock className="w-3.5 h-3.5 text-indigo-400" />
            Survey Duration
          </span>
          <div className="flex items-baseline gap-1 mt-auto">
            <span className="text-xl font-extrabold text-white font-mono">{durationSec}</span>
            <span className="text-xs text-slate-400 font-mono">SEC</span>
          </div>
        </div>

        {/* Total Hazards */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-lg p-3 flex flex-col">
          <span className="text-[11px] font-medium text-slate-400 flex items-center gap-1.5 mb-1">
            <BarChart3 className="w-3.5 h-3.5 text-amber-400" />
            Hazards Mapped
          </span>
          <div className="flex items-baseline gap-1 mt-auto">
            <span className="text-xl font-extrabold text-amber-400 font-mono">{totalCount}</span>
            <span className="text-xs text-slate-400 font-mono">EVENTS</span>
          </div>
        </div>

        {/* Critical Blocks */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-lg p-3 flex flex-col">
          <span className="text-[11px] font-medium text-slate-400 flex items-center gap-1.5 mb-1">
            <AlertOctagon className="w-3.5 h-3.5 text-red-400" />
            Critical Blockages
          </span>
          <div className="flex items-baseline gap-1 mt-auto">
            <span className="text-xl font-extrabold text-red-400 font-mono">{criticalCount}</span>
            <span className="text-xs text-slate-400 font-mono">URGENT</span>
          </div>
        </div>

        {/* Road Health Score */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-lg p-3 flex flex-col">
          <span className="text-[11px] font-medium text-slate-400 flex items-center gap-1.5 mb-1">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            Road Condition Index
          </span>
          <div className="flex items-baseline gap-1.5 mt-auto">
            <span className="text-xl font-extrabold text-white font-mono">{healthScore}</span>
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${getHealthColor(healthScore)}`}>
              {healthScore >= 80 ? 'OPTIMAL' : healthScore >= 50 ? 'CAUTION' : 'SEVERE'}
            </span>
          </div>
        </div>

      </div>

      {/* Severity Distribution Progress Bar */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-3">
        <div className="flex items-center justify-between text-xs text-slate-300 mb-2 font-medium">
          <span>Hazard Severity Composition</span>
          <span className="text-[11px] font-mono text-slate-400">
            {criticalCount} Critical | {highCount} High | {mediumCount} Medium | {lowCount} Low
          </span>
        </div>

        <div className="h-2.5 w-full bg-slate-800 rounded-full overflow-hidden flex">
          {totalCount > 0 ? (
            <>
              <div 
                style={{ width: `${(criticalCount / totalCount) * 100}%` }} 
                className="bg-red-500 h-full" 
                title={`Critical: ${criticalCount}`}
              />
              <div 
                style={{ width: `${(highCount / totalCount) * 100}%` }} 
                className="bg-orange-500 h-full" 
                title={`High: ${highCount}`}
              />
              <div 
                style={{ width: `${(mediumCount / totalCount) * 100}%` }} 
                className="bg-amber-400 h-full" 
                title={`Medium: ${mediumCount}`}
              />
              <div 
                style={{ width: `${(lowCount / totalCount) * 100}%` }} 
                className="bg-blue-500 h-full" 
                title={`Low: ${lowCount}`}
              />
            </>
          ) : (
            <div className="w-full bg-emerald-500 h-full" />
          )}
        </div>
      </div>
    </div>
  );
}
