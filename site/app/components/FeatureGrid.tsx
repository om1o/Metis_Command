const features = [
  {
    title: "Genius brain",
    body: "GLM-4.6 via Z.ai or local glm4:9b through Ollama. Auto-falls back to whichever is up.",
    letter: "G",
  },
  {
    title: "Brains",
    body: "Swappable long-term memory with episodic / semantic / procedural tiers. Auto-compacted — never forgets.",
    letter: "B",
  },
  {
    title: "Orchestrator Wallet",
    body: "Every cloud call and plugin is policy-gated. Hard monthly cap. Stripe Issuing ready.",
    letter: "$",
  },
  {
    title: "Agent roster",
    body: "12 specialists — scheduler, news digest, finance watch, shopper, travel agent, security auditor — each persistent.",
    letter: "A",
  },
  {
    title: "Daily plan",
    body: "Every morning the agents collate a briefing into your artifacts folder. Email delivery optional.",
    letter: "D",
  },
  {
    title: "100% local",
    body: "Runs on your hardware. Chat history, memory, identity — every byte stays on the machine.",
    letter: "L",
  },
];

export default function FeatureGrid() {
  return (
    <section className="max-w-6xl mx-auto px-6 py-20">
      <h2 className="font-serif text-4xl md:text-5xl text-center mb-12 tracking-tight">
        Built for <span className="gradient-text">daily operators</span>.
      </h2>
      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
        {features.map((f, i) => (
          <div
            key={f.title}
            className="group rounded-2xl border border-border bg-surface/80 backdrop-blur px-6 py-6 transition hover:-translate-y-0.5 hover:border-amber/40 hover:shadow-card animate-fadeUp"
            style={{ animationDelay: `${i * 60}ms` }}
          >
            <div
              className="w-9 h-9 rounded-full flex items-center justify-center font-serif text-bg0 mb-4"
              style={{
                background:
                  "linear-gradient(135deg,#E8A446 0%,#FF6B9D 45%,#8B6CFF 100%)",
              }}
            >
              {f.letter}
            </div>
            <div className="font-semibold text-text mb-1">{f.title}</div>
            <div className="text-sm text-muted leading-relaxed">{f.body}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
