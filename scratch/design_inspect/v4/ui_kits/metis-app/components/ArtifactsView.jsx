// ArtifactsView.jsx
const ARTIFACTS = [
  { id: 1, name: 'leads_q2.csv',         kind: 'csv',  size: '28 KB',   meta: '142 rows',           run: 'run_a91f4c', age: '2m ago',  status: 'saved'  },
  { id: 2, name: 'first_touch.md',       kind: 'md',   size: '4.2 KB',  meta: 'outreach playbook',  run: 'run_a91f4c', age: '2m ago',  status: 'synced' },
  { id: 3, name: 'lead_finder.py',       kind: 'code', size: '1.8 KB',  meta: 'reusable agent skill', run: 'run_a91f4c', age: '3m ago', status: 'saved'  },
  { id: 4, name: 'follow_up_seq.eml',    kind: 'eml',  size: '6.1 KB',  meta: '4-email sequence',   run: 'run_a91f4c', age: '4m ago',  status: 'synced' },
  { id: 5, name: 'competitor_brief.md',  kind: 'md',   size: '12 KB',   meta: 'with citations',     run: 'run_d51228', age: '1h ago',  status: 'synced' },
  { id: 6, name: 'icp_research.md',      kind: 'md',   size: '8.9 KB',  meta: 'sourced from 14 sites', run: 'run_d51228', age: '1h ago', status: 'synced' },
  { id: 7, name: 'pricing_chart.png',    kind: 'img',  size: '74 KB',   meta: '1280×720',           run: 'run_d51228', age: '2h ago',  status: 'synced' },
  { id: 8, name: 'meeting_notes.md',     kind: 'md',   size: '2.3 KB',  meta: 'auto-summarized',    run: 'run_e10421', age: 'yest.',   status: 'synced' },
];

const KIND_ICONS = {
  csv:  'sheet',
  md:   'file-text',
  code: 'code',
  eml:  'mail',
  img:  'image',
};

function ArtifactsView() {
  const [filter, setFilter] = React.useState('all');
  const filtered = filter === 'all' ? ARTIFACTS : ARTIFACTS.filter(a => a.kind === filter);
  return (
    <>
      <div className="filter-bar">
        {[
          { k: 'all',  l: 'All',         n: ARTIFACTS.length },
          { k: 'md',   l: 'Documents',   n: ARTIFACTS.filter(a => a.kind === 'md').length },
          { k: 'csv',  l: 'Data',        n: ARTIFACTS.filter(a => a.kind === 'csv').length },
          { k: 'code', l: 'Code',        n: ARTIFACTS.filter(a => a.kind === 'code').length },
          { k: 'eml',  l: 'Drafts',      n: ARTIFACTS.filter(a => a.kind === 'eml').length },
          { k: 'img',  l: 'Images',      n: ARTIFACTS.filter(a => a.kind === 'img').length },
        ].map(f => (
          <button key={f.k} className={`filter-chip ${filter === f.k ? 'active' : ''}`} onClick={() => setFilter(f.k)}>
            {f.l} <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, marginLeft: 4, opacity: .7 }}>{f.n}</span>
          </button>
        ))}
        <div style={{ flex: 1 }}></div>
        <Button variant="secondary" size="sm" leading="grid-2x2">Grid</Button>
        <Button variant="ghost"     size="sm" leading="list">List</Button>
      </div>

      <div className="artifact-grid">
        {filtered.map(a => (
          <Card key={a.id} hoverable selectable className="artifact-card">
            <div className="art-head">
              <div className={`art-iconbox ${a.kind}`}>
                <Icon name={KIND_ICONS[a.kind]} size={18} />
              </div>
              <Chip status={a.status}>{a.status === 'synced' ? 'Synced' : 'Saved'}</Chip>
            </div>
            <div>
              <div className="art-name">{a.name}</div>
              <div className="art-meta" style={{ marginTop: 4 }}>{a.size} · {a.meta}</div>
            </div>
            <div className="art-foot">
              <span className="id">{a.run}</span>
              <span>{a.age}</span>
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
window.ArtifactsView = ArtifactsView;
