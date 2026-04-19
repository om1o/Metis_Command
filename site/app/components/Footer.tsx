import Link from "next/link";

export default function Footer() {
  return (
    <footer className="max-w-6xl mx-auto px-6 py-16 border-t border-border mt-12">
      <div className="flex flex-wrap justify-between items-center text-sm text-muted gap-4">
        <div className="font-serif text-xl gradient-text">◆ Metis Command</div>
        <div className="flex gap-6">
          <Link href={process.env.METIS_GITHUB!} className="hover:text-text">
            GitHub
          </Link>
          <Link href="/api/download" className="hover:text-text">
            Download
          </Link>
          <a href="mailto:security@metis.systems" className="hover:text-text">
            security@
          </a>
        </div>
      </div>
      <div className="mt-6 text-[11px] font-mono text-muted">
        © Metis Systems 2026. Local-first. Your data never leaves the machine.
      </div>
    </footer>
  );
}
