// Settings.jsx
function Settings() {
  const [autosave, setAutosave] = React.useState(true);
  const [cloud, setCloud] = React.useState(true);
  const [local, setLocal] = React.useState(false);
  const [strict, setStrict] = React.useState(true);

  return (
    <div style={{ maxWidth: 760 }}>
      <Card className="settings-section">
        <div>
          <div className="ttl">Artifacts</div>
          <div className="desc">How runs save and sync their work.</div>
        </div>
        <div style={{ marginTop: 16 }}>
          <div className="settings-row">
            <div>
              <div className="label">Auto-save runs</div>
              <div className="hint">Every step writes to <span className="mono">~/metis/runs/</span> as it completes.</div>
            </div>
            <Toggle on={autosave} onChange={setAutosave} />
          </div>
          <div className="settings-row">
            <div>
              <div className="label">Mirror to cloud</div>
              <div className="hint">Sync artifacts to your linked storage. Encrypted at rest.</div>
            </div>
            <Toggle on={cloud} onChange={setCloud} />
          </div>
          <div className="settings-row">
            <div>
              <div className="label">Artifacts directory</div>
              <div className="hint mono" style={{ fontFamily: 'var(--font-mono)' }}>~/metis/runs/</div>
            </div>
            <Button variant="secondary" size="sm" trailing="folder-open">Change</Button>
          </div>
        </div>
      </Card>

      <Card className="settings-section">
        <div>
          <div className="ttl">Models & agents</div>
          <div className="desc">Choose where missions run. You can override per mission.</div>
        </div>
        <div style={{ marginTop: 16 }}>
          <div className="settings-row">
            <div>
              <div className="label">Default model</div>
              <div className="hint">Used when a mission doesn't specify one.</div>
            </div>
            <select className="input" style={{ width: 220 }} defaultValue="sonnet">
              <option value="sonnet">Claude Sonnet 4.5</option>
              <option value="opus">Claude Opus 4</option>
              <option value="gpt">GPT-4o</option>
              <option value="local">Local · Llama 3.1 70B</option>
            </select>
          </div>
          <div className="settings-row">
            <div>
              <div className="label">Local mode</div>
              <div className="hint">Route work to Ollama on this machine when possible.</div>
            </div>
            <Toggle on={local} onChange={setLocal} />
          </div>
        </div>
      </Card>

      <Card className="settings-section">
        <div>
          <div className="ttl">Guardrails</div>
          <div className="desc">What agents are allowed to do without asking.</div>
        </div>
        <div style={{ marginTop: 16 }}>
          <div className="settings-row">
            <div>
              <div className="label">Strict tool approval</div>
              <div className="hint">Confirm before agents run tools that touch the network or your filesystem.</div>
            </div>
            <Toggle on={strict} onChange={setStrict} />
          </div>
          <div className="settings-row">
            <div>
              <div className="label" style={{ color: 'var(--error)' }}>Reset workspace</div>
              <div className="hint">Clears all runs, artifacts, and memory. Cannot be undone.</div>
            </div>
            <Button variant="destructive" size="sm" leading="trash-2">Reset…</Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
window.Settings = Settings;
