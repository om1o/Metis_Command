// Chat.jsx
function Chat({ onShipped }) {
  const [thread, setThread] = React.useState([
    { from: 'agent', text: <>Welcome back. What should we ship today? Try a goal like <code>"find 30 fintech leads, draft outreach"</code>.</> },
  ]);
  const [draft, setDraft] = React.useState('');
  const [thinking, setThinking] = React.useState(false);
  const [shipped, setShipped] = React.useState(false);
  const threadRef = React.useRef(null);

  React.useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
  }, [thread, thinking]);

  const send = () => {
    const t = draft.trim();
    if (!t) return;
    setThread(prev => [...prev, { from: 'user', text: t }]);
    setDraft('');
    setThinking(true);
    setTimeout(() => {
      setThread(prev => [...prev, { from: 'agent', text: <>On it. I'll plan the steps, run the research, and save artifacts to <code>~/metis/run_e7211c/</code>.</> }]);
      setThinking(false);
      setTimeout(() => {
        setThread(prev => [...prev, { from: 'agent', text: <><b>Shipped.</b> 4 artifacts written. <a href="#" style={{ color: 'inherit', textDecoration: 'underline' }} onClick={(e) => { e.preventDefault(); onShipped?.(); }}>View in Artifacts →</a></> }]);
        setShipped(true);
        onShipped?.('toast');
      }, 2200);
    }, 1100);
  };

  return (
    <div className="chat-wrap">
      <div className="thread" ref={threadRef}>
        {thread.map((m, i) => (
          <div key={i} className={`bubble bubble-${m.from}`}>{m.text}</div>
        ))}
        {thinking && (
          <div className="thinking">
            <span>Routing to research agent</span>
            <span className="thinking-dot"></span><span className="thinking-dot"></span><span className="thinking-dot"></span>
          </div>
        )}
      </div>

      <div className="composer">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Give Metis a goal. It'll plan, run, and save the artifacts."
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); } }}
        />
        <div className="composer-row">
          <button className="iconbtn" title="Attach file"><Icon name="paperclip" size={18} /></button>
          <button className="iconbtn" title="Add tool"><Icon name="wrench" size={18} /></button>
          <span className="chip chip-ready" style={{ marginLeft: 4 }}>
            <Icon name="cpu" size={12} style={{ color: 'var(--text-muted)' }} />
            Sonnet 4.5
          </span>
          <span className="chip chip-saved"><span className="chip-dot"></span>Auto-save on</span>
          <div className="right">
            <span className="kbd">⌘ ↵</span>
            <Button variant="primary" leading="send" onClick={send} disabled={!draft.trim()}>Run</Button>
          </div>
        </div>
      </div>
    </div>
  );
}
window.Chat = Chat;
