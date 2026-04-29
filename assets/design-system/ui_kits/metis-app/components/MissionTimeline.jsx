// MissionTimeline.jsx
const MISSION_STEPS = [
  { id: 1, status: 'done', title: 'Plan the mission',                    meta: 'routed to planner agent · 4 sub-tasks',           dur: '2s' },
  { id: 2, status: 'done', title: 'Search Crunchbase for fintech Series A 2024', meta: '42 candidates · narrowed to 30',          dur: '38s' },
  { id: 3, status: 'run',  title: 'Draft first-touch emails',            meta: '14 / 30 written…',                                dur: 'running' },
  { id: 4, status: 'todo', title: 'Save artifacts',                      meta: 'leads_q2.csv · drafts/*.eml',                     dur: '—' },
  { id: 5, status: 'todo', title: 'Sync to cloud',                       meta: 'mirror to ~/cloud/metis/',                        dur: '—' },
];

function MissionTimeline({ onCancel }) {
  return (
    <Card className="mission-card">
      <div className="mission-head">
        <div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 6 }}>
            <Chip status="running">Running</Chip>
            <span className="chip chip-saved"><span className="chip-dot"></span>Auto-saved</span>
          </div>
          <div className="ttl">Outreach — fintech ICP</div>
          <div className="meta">
            <span>run_b2c81d</span>
            <span>started 14s ago</span>
            <span>Sonnet 4.5</span>
            <span>$0.041 · 3,210 tokens</span>
          </div>
        </div>
        <div className="row">
          <Button variant="secondary" size="sm" leading="pause">Pause</Button>
          <Button variant="ghost"     size="sm" leading="x" onClick={onCancel}>Stop</Button>
        </div>
      </div>

      <div className="steps">
        {MISSION_STEPS.map((s, i) => (
          <div className="step-row" key={s.id}>
            <div className="step-bullet-col">
              <div className={`step-bullet ${s.status}`}>
                {s.status === 'done' ? '✓' : s.status === 'fail' ? '×' : s.id}
              </div>
              {i < MISSION_STEPS.length - 1 && <div className="step-line"></div>}
            </div>
            <div>
              <div className="step-title">{s.title}</div>
              <div className="step-meta">{s.meta}</div>
            </div>
            <div className="step-dur">{s.dur}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 24, paddingTop: 20, borderTop: '1px solid var(--border)', alignItems: 'center' }}>
        <Icon name="terminal" size={16} style={{ color: 'var(--text-muted)' }} />
        <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>Logs streaming · 142 lines</span>
        <div style={{ flex: 1 }}></div>
        <Button variant="ghost" size="sm" trailing="external-link">Open logs</Button>
      </div>
    </Card>
  );
}
window.MissionTimeline = MissionTimeline;
