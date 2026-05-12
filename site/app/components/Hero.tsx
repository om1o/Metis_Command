import DownloadButton from "./DownloadButton";
import Link from "next/link";

export default function Hero() {
  return (
    <section className="max-w-6xl mx-auto px-6 pt-24 pb-16 text-center">
      <div className="flex items-center justify-center mb-8 animate-fadeUp">
        <span className="inline-flex items-center gap-2 text-xs font-mono text-muted border border-border rounded-full px-3 py-1">
          <span className="w-1.5 h-1.5 rounded-full bg-amber animate-breath" />
          v{process.env.METIS_VERSION} · Windows build available
        </span>
      </div>

      <h1 className="font-serif text-5xl md:text-7xl leading-[1.05] tracking-tight animate-fadeUp">
        Your AI, running on{" "}
        <span className="gradient-text">your machine</span>.
      </h1>

      <p className="mt-6 text-lg text-muted max-w-2xl mx-auto animate-fadeUp">
        Metis Command is a local-first autonomous AI desktop. A five-agent
        swarm with persistent memory, a policy-gated wallet, and a daily plan
        written by the agents themselves — every byte stays on your hardware.
      </p>

      <div className="mt-10 flex flex-col md:flex-row gap-3 justify-center items-center animate-fadeUp">
        <DownloadButton />
        <Link
          href={process.env.METIS_GITHUB!}
          className="text-sm text-muted hover:text-text transition px-5 py-3 rounded-full border border-border hover:border-amber/40"
        >
          View on GitHub →
        </Link>
      </div>

      <div className="mt-12 font-mono text-[11px] text-muted animate-fadeUp">
        100% local · Ollama-powered · Optional GLM-4.6 cloud genius
      </div>
    </section>
  );
}
