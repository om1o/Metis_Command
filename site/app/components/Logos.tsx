export default function Logos() {
  const stacks = [
    "ollama", "qwen2.5-coder", "deepseek-r1", "llama3.2",
    "glm-4.6", "llava", "chromadb", "crewai",
  ];
  return (
    <section className="max-w-5xl mx-auto px-6 py-12">
      <div className="text-center text-xs font-mono uppercase tracking-widest text-muted mb-6">
        Powered by open local models
      </div>
      <div className="flex flex-wrap justify-center gap-3 text-[13px] font-mono text-text/80">
        {stacks.map((n) => (
          <span
            key={n}
            className="px-3 py-1.5 rounded-full bg-surface/70 border border-border"
          >
            {n}
          </span>
        ))}
      </div>
    </section>
  );
}
