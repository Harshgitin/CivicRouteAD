import React, { useEffect, useState } from 'react';
import { 
  X, 
  FileText, 
  Printer, 
  Download, 
  AlertOctagon, 
  CheckCircle2, 
  Building2, 
  Route 
} from 'lucide-react';
import { fetchReport } from '../utils/api';

export default function ReportModal({ isOpen, onClose, runId }) {
  const [report, setReport] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (isOpen && runId) {
      setIsLoading(true);
      fetchReport(runId)
        .then((data) => {
          setReport(data);
          setIsLoading(false);
        })
        .catch(() => setIsLoading(false));
    }
  }, [isOpen, runId]);

  if (!isOpen) return null;

  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-[#111827] border border-slate-700 rounded-2xl max-w-3xl w-full max-h-[90vh] flex flex-col overflow-hidden shadow-2xl">
        
        {/* Header */}
        <div className="bg-slate-900 border-b border-slate-800 p-4 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-amber-500/20 text-amber-400 rounded-lg">
              <FileText className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white">Municipal Road Hazard Action Plan</h3>
              <p className="text-[11px] text-slate-400">Emergency dispatch & public works work order</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handlePrint}
              className="flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs px-3 py-1.5 rounded-lg border border-slate-700 transition-colors"
            >
              <Printer className="w-3.5 h-3.5" />
              <span>Print Plan</span>
            </button>
            <button
              onClick={onClose}
              className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Report Content Scrollable */}
        <div className="flex-1 overflow-y-auto p-6 font-sans space-y-6 bg-slate-950/50">
          
          {isLoading || !report ? (
            <div className="text-center py-12 text-slate-400 text-xs font-mono">
              Generating Municipal Action Report...
            </div>
          ) : (
            <>
              {/* Document Title Header */}
              <div className="border-b border-slate-800 pb-4">
                <div className="flex items-center gap-2 text-cyan-400 text-xs font-bold uppercase tracking-wider mb-1">
                  <Building2 className="w-4 h-4" />
                  <span>{report.organization}</span>
                </div>
                <h2 className="text-xl font-extrabold text-white tracking-tight">
                  {report.title}
                </h2>
                <div className="flex flex-wrap items-center gap-4 text-xs font-mono text-slate-400 mt-2">
                  <span>RUN ID: {report.run_id}</span>
                  <span>GENERATED: {new Date().toLocaleString()}</span>
                </div>
              </div>

              {/* Route Survey Metrics */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 grid grid-cols-2 sm:grid-cols-4 gap-4 text-center">
                <div>
                  <span className="text-[11px] text-slate-400 block mb-1">Route Length</span>
                  <span className="text-lg font-bold text-white font-mono">{report.route_summary.total_distance_km} KM</span>
                </div>
                <div>
                  <span className="text-[11px] text-slate-400 block mb-1">Survey Duration</span>
                  <span className="text-lg font-bold text-white font-mono">{report.route_summary.survey_duration_sec}s</span>
                </div>
                <div>
                  <span className="text-[11px] text-slate-400 block mb-1">Average Velocity</span>
                  <span className="text-lg font-bold text-white font-mono">{report.route_summary.average_speed_kmh} KM/H</span>
                </div>
                <div>
                  <span className="text-[11px] text-slate-400 block mb-1">Total Hazards</span>
                  <span className="text-lg font-bold text-amber-400 font-mono">{report.route_summary.total_hazards_logged}</span>
                </div>
              </div>

              {/* Critical Priority Items */}
              <div className="space-y-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-red-400 flex items-center gap-2">
                  <AlertOctagon className="w-4 h-4" />
                  Priority 1: Immediate Emergency Roadway Clearance
                </h4>

                {report.critical_action_items.length === 0 ? (
                  <p className="text-xs text-slate-400 italic">No critical hazards requiring immediate emergency road shutdown.</p>
                ) : (
                  <div className="space-y-2">
                    {report.critical_action_items.map((item) => (
                      <div key={item.hazard_id} className="p-3 bg-red-950/20 border border-red-500/30 rounded-lg flex flex-col gap-1">
                        <div className="flex items-center justify-between text-xs">
                          <span className="font-bold font-mono text-white">{item.hazard_id}: {item.category.replace(/_/g, ' ').toUpperCase()}</span>
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-500/30 text-red-300 border border-red-500/50">
                            {item.severity}
                          </span>
                        </div>
                        <div className="text-[11px] font-mono text-slate-300">
                          Coords: <span className="text-cyan-300">{item.location_coords}</span> | Lane: {item.lane_position}
                        </div>
                        <p className="text-xs text-slate-300 mt-1">
                          <strong className="text-red-300">Dispatch Directive:</strong> {item.recommended_dispatch}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Routine Maintenance Items */}
              <div className="space-y-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-amber-400 flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4" />
                  Priority 2: Department of Transportation Repair Work Orders
                </h4>

                {report.routine_maintenance_items.length === 0 ? (
                  <p className="text-xs text-slate-400 italic">No secondary maintenance items logged.</p>
                ) : (
                  <div className="space-y-2">
                    {report.routine_maintenance_items.map((item) => (
                      <div key={item.hazard_id} className="p-3 bg-slate-900 border border-slate-800 rounded-lg flex flex-col gap-1">
                        <div className="flex items-center justify-between text-xs">
                          <span className="font-bold font-mono text-white">{item.hazard_id}: {item.category.replace(/_/g, ' ').toUpperCase()}</span>
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40">
                            {item.severity}
                          </span>
                        </div>
                        <div className="text-[11px] font-mono text-slate-400">
                          Coords: <span className="text-cyan-300">{item.location_coords}</span> | Lane: {item.lane_position}
                        </div>
                        <p className="text-xs text-slate-300 mt-1">
                          <strong className="text-amber-300">Directive:</strong> {item.recommended_dispatch}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

            </>
          )}

        </div>

      </div>
    </div>
  );
}
