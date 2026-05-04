// App.jsx — Metis App UI Kit demo
const { useState, useEffect } = React;

function App() {
  const [view, setView] = useState('chat');
  const [activeMission, setActiveMission] = useState('run_b2c81d');
  const [toasts, setToasts] = useState([]);

  useEffect(() => {
    if (window.lucide) window.lucide.createIcons();
  });

  const showToast = (text) => {
    const id = Date.now();
    setToasts(prev => [...prev, { id, text }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 2800);
  };

  const handleNav = (id) => {
    setView(id);
  };

  const handleShipped = (mode) => {
    if (mode === 'toast') showToast('Shipped. 4 artifacts saved.');
    else setView('artifacts');
  };

  const titles = {
    chat: 'Chat',
    missions: 'Mission Control',
    artifacts: 'Artifacts',
    agents: 'Agents',
    settings: 'Settings',
  };

  return (
    <div className="shell">
      <Sidebar
        active={view}
        onNav={handleNav}
        activeMission={activeMission}
        onSelectMission={(id) => { setActiveMission(id); setView('missions'); }}
      />
      <div className="main">
        <Topbar title={titles[view]} />
        <div className="content">
          {view === 'chat' && (
            <>
              <div className="page-head">
                <div>
                  <div className="h">What should we ship today?</div>
                  <div className="sub">Give Metis a goal. It plans, runs, and saves the artifacts.</div>
                </div>
                <div className="row">
                  <Button variant="ghost" size="sm" leading="history">History</Button>
                  <Button variant="secondary" size="sm" leading="bookmark">Save as skill</Button>
                </div>
              </div>
              <Chat onShipped={handleShipped} />
            </>
          )}

          {view === 'missions' && (
            <>
              <div className="page-head">
                <div>
                  <div className="h">Mission Control</div>
                  <div className="sub">Live runs, with logs and artifacts. Like a workout plan — every step accounted for.</div>
                </div>
                <Button variant="primary" leading="plus">New mission</Button>
              </div>
              <MissionTimeline onCancel={() => showToast('Run paused.')} />
            </>
          )}

          {view === 'artifacts' && (
            <>
              <div className="page-head">
                <div>
                  <div className="h">Artifacts</div>
                  <div className="sub">Every run's output, saved and synced.</div>
                </div>
                <div className="row">
                  <Button variant="secondary" size="sm" leading="cloud-upload">Sync now</Button>
                  <Button variant="primary"   size="sm" leading="folder-open">Open in Finder</Button>
                </div>
              </div>
              <ArtifactsView />
            </>
          )}

          {view === 'agents' && (
            <>
              <div className="page-head">
                <div>
                  <div className="h">Agents</div>
                  <div className="sub">Specialized roles routed by missions.</div>
                </div>
              </div>
              <div className="empty">
                <div className="empty-art"><Icon name="bot" size={42} /></div>
                <h3>Build your team</h3>
                <p>Agents are reusable roles — researcher, planner, coder, communicator. Each one bundles a model, system prompt, and tool set.</p>
                <Button variant="primary" leading="plus" style={{ marginTop: 12 }}>Create an agent</Button>
              </div>
            </>
          )}

          {view === 'settings' && (
            <>
              <div className="page-head">
                <div>
                  <div className="h">Settings</div>
                  <div className="sub">Defaults for every run. Override per mission as needed.</div>
                </div>
              </div>
              <Settings />
            </>
          )}
        </div>
      </div>

      <div className="toast-stack">
        {toasts.map(t => (
          <div key={t.id} className="toast">
            <span className="check"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg></span>
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
