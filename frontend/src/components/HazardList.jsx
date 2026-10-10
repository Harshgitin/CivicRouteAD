import React, { useState } from 'react';
import { 
  AlertTriangle, 
  MapPin, 
  Clock, 
  Search, 
  Eye, 
  Play, 
  AlertOctagon, 
  CheckCircle, 
  ShieldAlert,
  ArrowRight
} from 'lucide-react';

export default function HazardList({ 
  hazards = [], 
  selectedHazard, 
  onSelectHazard, 
  onSeekToHazard 
}) {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedSeverity, setSelectedSeverity] = useState('ALL');
  const [modalImage, setModalImage] = useState(null);

  const filtered = hazards.filter((h) => {
    const matchesSearch = 
      h.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      h.type.toLowerCase().includes(searchTerm.toLowerCase()) ||
      h.lane_location?.toLowerCase().includes(searchTerm.toLowerCase());

    const matchesSeverity = selectedSeverity === 'ALL' || h.severity === selectedSeverity;
    return matchesSearch && matchesSeverity;
  });

  const getSeverityBadge = (severity) => {
    switch (severity) {
      case 'Critical':
        return 'bg-red-500/20 text-red-400 border-red-500/40';
      case 'High':
        return 'bg-orange-500/20 text-orange-400 border-orange-500/40';
      case 'Medium':
        return 'bg-amber-500/20 text-amber-400 border-amber-500/40';
      default:
        return 'bg-blue-500/20 text-blue-400 border-blue-500/40';
    }
  };

  return (
    <div className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden shadow-2xl flex flex-col h-full">
      {/* Header & Search */}
      <div className="bg-slate-900 border-b border-slate-800 p-3 flex flex-col gap-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-4 h-4 text-amber-400" />
            <h3 className="text-xs font-bold text-white uppercase tracking-wider">
              Hazard Incident Register
            </h3>
          </div>
          <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
            {filtered.length} of {hazards.length} Logged
          </span>
        </div>

        {/* Search & Filter Bar */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Filter by ID, hazard type, lane..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-8 pr-3 py-1 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div className="flex items-center gap-1 bg-slate-800 border border-slate-700 rounded-lg p-0.5 text-[11px]">
            {['ALL', 'Critical', 'High', 'Medium'].map((sev) => (
              <button
                key={sev}
                onClick={() => setSelectedSeverity(sev)}
                className={`px-2 py-0.5 rounded transition-colors ${
                  selectedSeverity === sev
                    ? 'bg-blue-600 text-white font-bold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {sev}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Hazard Cards Scroll Area */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2.5 max-h-[520px]">
        {filtered.length === 0 ? (
          <div className="text-center py-10 text-slate-500 text-xs">
            No road hazards matching your current search criteria.
          </div>
        ) : (
          filtered.map((h) => {
            const isSelected = selectedHazard?.id === h.id;
            return (
              <div
                key={h.id}
                onClick={() => onSelectHazard(h)}
                className={`p-3 rounded-lg border transition-all cursor-pointer flex gap-3 ${
                  isSelected
                    ? 'bg-blue-950/40 border-blue-500 shadow-md shadow-blue-500/10'
                    : 'bg-slate-900/70 border-slate-800 hover:border-slate-700 hover:bg-slate-800/50'
                }`}
              >
                {/* Crop Snapshot Thumbnail */}
                <div 
                  onClick={(e) => {
                    e.stopPropagation();
                    if (h.snapshot_url) setModalImage(h.snapshot_url);
                  }}
                  className="w-20 h-16 rounded-md bg-black border border-slate-700 overflow-hidden shrink-0 relative group flex items-center justify-center"
                >
                  {h.snapshot_url ? (
                    <>
                      <img src={h.snapshot_url} alt={h.id} className="w-full h-full object-cover" />
                      <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity">
                        <Eye className="w-4 h-4 text-white" />
                      </div>
                    </>
                  ) : (
                    <AlertTriangle className="w-6 h-6 text-slate-600" />
                  )}
                </div>

                {/* Info Column */}
                <div className="flex-1 min-w-0 flex flex-col justify-between">
                  <div>
                    <div className="flex items-center justify-between gap-1 mb-1">
                      <span className="font-mono text-xs font-bold text-white">{h.id}</span>
                      <div className="flex items-center gap-1">
                        <span className={`text-[9px] font-mono px-1.5 py-0.2 rounded border ${
                          h.verification === 'model_inferred' 
                            ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40' 
                            : 'bg-slate-800 text-slate-400 border-slate-700'
                        }`}>
                          {h.verification === 'model_inferred' ? 'Model Inferred' : 'Heuristic'}
                        </span>
                        <span className={`text-[10px] font-bold px-2 py-0.2 rounded-full border ${getSeverityBadge(h.severity)}`}>
                          {h.severity}
                        </span>
                      </div>
                    </div>

                    <h4 className="text-xs font-semibold text-cyan-300 truncate">
                      {(h.label || h.type.replace(/_/g, ' ')).toUpperCase()}
                    </h4>
                  </div>

                  <div className="grid grid-cols-2 gap-x-2 text-[10px] font-mono text-slate-400 mt-1">
                    <div>Dist: <span className="text-slate-200">{h.forward_distance_m}m</span></div>
                    <div>Conf: <span className="text-emerald-400">{Math.round(h.confidence * 100)}%</span></div>
                    <div className="col-span-2 text-slate-400 truncate" title={h.location_quality || 'Approximate camera projection'}>
                      {h.lane_location} • {h.location_quality?.includes('unvalidated') || h.location_quality === 'unanchored_out_of_gps_coverage'
                        ? 'approximate location · accuracy not established'
                        : h.estimated_uncertainty_m != null && Number.isFinite(Number(h.estimated_uncertainty_m))
                          ? `indicative ±${Number(h.estimated_uncertainty_m).toFixed(1)}m`
                          : 'approximate location · accuracy not established'}
                    </div>
                  </div>

                  {/* Quick Action Button */}
                  <div className="mt-2 flex items-center justify-between pt-1.5 border-t border-slate-800/80">
                    <span className="text-[10px] text-slate-500 font-mono">
                      @ {h.timestamp_sec}s
                    </span>

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onSeekToHazard(h);
                      }}
                      className="flex items-center gap-1 text-[11px] font-medium text-blue-400 hover:text-blue-300 transition-colors"
                    >
                      <span>Locate in Video</span>
                      <ArrowRight className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Image Modal Lightbox */}
      {modalImage && (
        <div 
          onClick={() => setModalImage(null)}
          className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4"
        >
          <div className="bg-slate-900 border border-slate-700 rounded-xl max-w-xl w-full p-4 overflow-hidden shadow-2xl">
            <h4 className="text-sm font-bold text-white mb-2">High-Resolution Hazard Visual Inspection</h4>
            <div className="rounded-lg overflow-hidden border border-slate-800 bg-black aspect-video flex items-center justify-center">
              <img src={modalImage} alt="Crop" className="max-w-full max-h-full object-contain" />
            </div>
            <button
              onClick={() => setModalImage(null)}
              className="mt-3 w-full bg-slate-800 hover:bg-slate-700 text-white text-xs font-semibold py-2 rounded-lg"
            >
              Close Snapshot
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
