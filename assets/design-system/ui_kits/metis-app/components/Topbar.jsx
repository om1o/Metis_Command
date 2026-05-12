// Topbar.jsx
function Topbar({ title }) {
  return (
    <header className="topbar">
      <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 15, color: 'var(--text)' }}>{title}</div>
      <div className="search-wrap" style={{ marginLeft: 24 }}>
        <Icon name="search" size={16} />
        <input className="input" placeholder="Search runs, artifacts, agents…" />
        <span className="kbd" style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)' }}>⌘K</span>
      </div>
      <div className="tb-right">
        <span className="chip chip-running"><span className="chip-dot"></span>1 running</span>
        <button className="iconbtn" aria-label="Notifications"><Icon name="bell" size={18} /></button>
        <button className="iconbtn" aria-label="Help"><Icon name="circle-help" size={18} /></button>
      </div>
    </header>
  );
}
window.Topbar = Topbar;
