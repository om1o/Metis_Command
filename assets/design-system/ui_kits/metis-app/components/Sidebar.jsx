// Sidebar.jsx
const SIDEBAR_NAV = [
  { id: 'chat',      label: 'Chat',      icon: 'message-square', count: null },
  { id: 'missions',  label: 'Missions',  icon: 'target',         count: 14 },
  { id: 'artifacts', label: 'Artifacts', icon: 'folder-open',    count: 142 },
  { id: 'agents',    label: 'Agents',    icon: 'bot',            count: 6 },
  { id: 'settings',  label: 'Settings',  icon: 'settings-2',     count: null },
];

const RECENT_MISSIONS = [
  { id: 'run_a91f4c', ttl: 'Outreach — fintech ICP',   status: 'synced' },
  { id: 'run_b2c81d', ttl: 'Competitor brief',         status: 'running' },
  { id: 'run_c4081e', ttl: 'API research',             status: 'failed' },
  { id: 'run_d51228', ttl: 'Q2 board prep',            status: 'saved' },
];

function Sidebar({ active, onNav, activeMission, onSelectMission }) {
  return (
    <aside className="sidebar">
      <div className="sb-head">
        <div className="mark">
          <svg viewBox="0 0 64 64"><path d="M32 4 L36 28 L60 32 L36 36 L32 60 L28 36 L4 32 L28 28 Z" /></svg>
        </div>
        <div className="name">Metis</div>
        <div style={{ marginLeft: 'auto' }}>
          <span className="chip chip-synced"><span className="chip-dot"></span>Synced</span>
        </div>
      </div>

      <div style={{ padding: '12px 12px 0' }}>
        <Button variant="primary" leading="plus" style={{ width: '100%' }}>New mission</Button>
      </div>

      <div className="sb-section">Workspace</div>
      <nav className="sb-nav">
        {SIDEBAR_NAV.map(item => (
          <button
            key={item.id}
            className={`sb-item ${active === item.id ? 'active' : ''}`}
            onClick={() => onNav(item.id)}
          >
            <Icon name={item.icon} size={18} />
            <span>{item.label}</span>
            {item.count != null && <span className="count">{item.count}</span>}
          </button>
        ))}
      </nav>

      <div className="sb-section">Recent missions</div>
      <div style={{ padding: '0 8px', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {RECENT_MISSIONS.map(m => (
          <div
            key={m.id}
            className={`sb-mission ${activeMission === m.id ? 'active' : ''}`}
            onClick={() => onSelectMission?.(m.id)}
          >
            <span className={`chip chip-${m.status}`} style={{ padding: 0, background: 'transparent' }}>
              <span className="chip-dot" style={{ width: 7, height: 7 }}></span>
            </span>
            <div>
              <div className="ttl">{m.ttl}</div>
              <div className="id">{m.id}</div>
            </div>
            <Icon name="chevron-right" size={14} style={{ color: 'var(--text-subtle)' }} />
          </div>
        ))}
      </div>

      <div className="sb-foot">
        <div className="row" style={{ padding: '4px 4px' }}>
          <div className="avatar">YC</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>You</div>
            <div style={{ fontSize: 11.5, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>operator · pro</div>
          </div>
          <Icon name="more-horizontal" size={16} style={{ color: 'var(--text-subtle)' }} />
        </div>
      </div>
    </aside>
  );
}

window.Sidebar = Sidebar;
