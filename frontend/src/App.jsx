import React, { useState } from 'react';
import { Activity, ArrowUpRight, Building2, CircleHelp, FileVideo2, Layers3, MapPinned, ShieldCheck } from 'lucide-react';
import PublicReportPage from './components/PublicReportPage';
import StaffReportsPage from './components/StaffReportsPage';
import AnalysisConsole from './AnalysisConsole';
import AdvancedInfrastructurePage from './components/AdvancedInfrastructurePage';

const NAV_ITEMS = [
  { id: 'report', label: 'Report a problem', icon: FileVideo2 },
  { id: 'staff', label: 'Staff workspace', icon: ShieldCheck },
  { id: 'lab', label: 'Analysis lab', icon: Activity },
  { id: 'advanced', label: 'Advanced', icon: Layers3 },
];

export default function App() {
  const [activeView, setActiveView] = useState('report');

  return (
    <div className="site-app">
      <header className="site-header">
        <button className="brand-lockup" onClick={() => setActiveView('report')} aria-label="CivicRoute home">
          <span className="brand-mark"><MapPinned size={22} strokeWidth={2.2} /></span>
          <span className="brand-copy"><strong>CivicRoute<span>AD</span></strong><small>Infrastructure, made visible.</small></span>
        </button>
        <nav className="main-navigation" aria-label="Main navigation">
          {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => setActiveView(id)} className={`nav-item ${activeView === id ? 'nav-item-active' : ''}`}>
              <Icon size={17} /> <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="header-status"><span className="header-status-dot" /> <span>Reporting portal</span></div>
      </header>

      {activeView === 'report' && <PublicReportPage />}
      {activeView === 'staff' && <StaffReportsPage />}
      {activeView === 'lab' && <main className="analysis-lab-shell"><section className="analysis-lab-intro"><div><div className="section-kicker">TECHNICAL REVIEW · DEMO FIXTURES</div><h1>Video &amp; map analysis lab</h1><p>Use this separate workspace to test the computer-vision pipeline with bundled demo scenarios or upload a video that has a matching GPX/CSV track. Public reports stay in the staff workspace.</p></div><span className="demo-data-pill"><span /> DEMO DATA IS LABELED</span></section><AnalysisConsole /></main>}
      {activeView === 'advanced' && <AdvancedInfrastructurePage />}

      <footer className="site-footer">
        <div className="footer-brand"><span className="footer-brand-mark"><Building2 size={17} /></span><strong>CivicRouteAD</strong><span>Community infrastructure reporting</span></div>
        <div className="footer-disclaimer"><CircleHelp size={14} /> Submissions and automated findings are unverified until reviewed by staff.</div>
        <button onClick={() => setActiveView('staff')} className="footer-staff-link">Staff access <ArrowUpRight size={13} /></button>
      </footer>
    </div>
  );
}
