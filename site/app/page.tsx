import Image from "next/image";
import Link from "next/link";
import DownloadButton from "./components/DownloadButton";
import {
  METIS_PRODUCT_NAME,
  METIS_RELEASES_URL,
  METIS_SUPPORT_URL,
  metisVersion,
} from "@/lib/brand";

export default function Page() {
  const version = metisVersion();

  return (
    <main className="relative z-10 flex min-h-screen flex-col items-center justify-center text-center px-6 py-20">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-white/5 via-transparent to-transparent opacity-50 pointer-events-none" />

      <div className="animate-fadeUp flex flex-col items-center max-w-2xl">
        <div className="mb-8 w-28 h-28 relative rounded-3xl overflow-hidden border border-white/10 p-2 bg-white/5 backdrop-blur-2xl shadow-[0_0_80px_rgba(255,255,255,0.07)]">
          <Image
            src="/logo.png"
            alt={`${METIS_PRODUCT_NAME} logo`}
            width={112}
            height={112}
            className="object-contain w-full h-full drop-shadow-2xl"
            priority
          />
        </div>

        <p className="text-xs font-mono opacity-50 tracking-widest uppercase mb-3">
          {METIS_PRODUCT_NAME} · v{version}
        </p>

        <h1 className="font-serif text-5xl md:text-7xl leading-tight tracking-tight mb-6 mt-0">
          {METIS_PRODUCT_NAME}
        </h1>

        <p className="text-xl md:text-2xl text-muted/90 font-light tracking-wide mb-8 max-w-lg">
          A desktop AI workspace: chat, memory, and tools running where{" "}
          <strong>you</strong> control the machine—local models via Ollama, optional
          cloud keys, and a local API for scripts and other apps.
        </p>

        <p className="text-sm text-muted/80 max-w-md mb-8 leading-relaxed">
          <strong>What you get:</strong> the Streamlit UI, agent roster, wallet
          gating, brain backup (.mts), plugins, and localhost API—not a
          subscription to a black-box cloud only.
        </p>

        <div className="w-full max-w-md rounded-2xl border border-white/10 bg-white/5 p-5 text-left mb-8">
          <p className="text-xs font-mono opacity-50 uppercase tracking-wider mb-2">
            System requirements
          </p>
          <ul className="text-sm text-muted/90 space-y-1.5 list-disc list-inside">
            <li>Windows 10/11 (64-bit) for the official build</li>
            <li>Python 3.12+ if you run from source; installer bundles its own runtime</li>
            <li>Ollama (recommended) for local models—see FAQ</li>
            <li>~4 GB+ free disk for a typical local model (varies by tier)</li>
          </ul>
        </div>

        <div className="flex flex-col items-center gap-4 mt-2">
          <DownloadButton />
          <p className="text-sm font-mono opacity-50 tracking-wider uppercase text-muted">
            Local-first · You own the data path
          </p>
        </div>

        <div className="w-full max-w-md mt-10 p-4 rounded-xl border border-amber-500/20 bg-amber-500/5 text-left">
          <p className="text-sm font-medium text-amber-200/90 mb-1">
            Windows SmartScreen: “Unknown publisher”
          </p>
          <p className="text-xs text-muted/90 leading-relaxed">
            We are not Microsoft-signed yet—Windows may warn on first run.
            If you downloaded from this site or our{" "}
            <a
              href={METIS_RELEASES_URL}
              className="underline underline-offset-2 hover:text-white"
            >
              GitHub Releases
            </a>
            , use “More info” → “Run anyway,” or verify the file hash on the
            release page before you run it.
          </p>
        </div>

        <nav className="flex flex-wrap items-center justify-center gap-4 text-sm text-muted/80 mt-10">
          <Link href="/faq" className="hover:text-white underline-offset-4 hover:underline">
            FAQ
          </Link>
          <span className="opacity-30">·</span>
          <a
            href={METIS_SUPPORT_URL}
            className="hover:text-white underline-offset-4 hover:underline"
            rel="noopener noreferrer"
          >
            Support (Discussions)
          </a>
          <span className="opacity-30">·</span>
          <a
            href={METIS_RELEASES_URL}
            className="hover:text-white underline-offset-4 hover:underline"
            rel="noopener noreferrer"
          >
            Releases &amp; checksums
          </a>
        </nav>
      </div>
    </main>
  );
}
