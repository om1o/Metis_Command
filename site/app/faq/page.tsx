import Link from "next/link";
import {
  METIS_PRODUCT_NAME,
  METIS_DISCUSSIONS_URL,
  METIS_RELEASES_URL,
} from "@/lib/brand";

export const metadata = {
  title: `FAQ — ${METIS_PRODUCT_NAME}`,
  description: "Ollama, Windows SmartScreen, firewall, API, reinstall.",
};

const items: { q: string; a: string }[] = [
  {
    q: "Do I need Ollama?",
    a: "For local models, yes: install Ollama from ollama.com and pull the models your tier uses. The app can still run for UI and some features; brain features that call Ollama will fail until it is up.",
  },
  {
    q: "Windows says “Windows protected your PC” or “Unknown publisher”",
    a: "Early builds are often unsigned. Click “More info” then “Run anyway” if you trust the download. Prefer verifying the file: compare SHA256 on the GitHub release page, or re-download from the official site. Signing with a real certificate is on the roadmap.",
  },
  {
    q: "Firewall or antivirus blocks Metis",
    a: "Allow the app for private networks if prompted. The local API binds to 127.0.0.1; allow localhost traffic. If an AV quarantines Metis.exe, add an exception or re-download from Releases after checking SHA256.",
  },
  {
    q: "“Can’t connect to API” or 401 on /wallet",
    a: "The local API uses a token on disk. In the app sidebar → Developer, copy the Bearer token and use it in clients. 401 means missing or wrong Authorization header.",
  },
  {
    q: "Reinstall or upgrade cleanly",
    a: "Download the latest asset from GitHub Releases. Run the new installer on top, or uninstall from Windows Settings first if you want a clean Program Files folder. Your data usually lives in user profile / project folders, not only in the install path—back up identity/ and .env if you customized them.",
  },
];

export default function FAQPage() {
  return (
    <main className="min-h-screen px-6 py-16 max-w-2xl mx-auto text-left">
      <p className="text-sm text-muted font-mono mb-4">
        <Link href="/" className="hover:underline">
          ← Home
        </Link>{" "}
        ·{" "}
        <Link href="/support" className="hover:underline">
          Support
        </Link>
      </p>
      <h1 className="font-serif text-3xl md:text-4xl mb-2">FAQ</h1>
      <p className="text-sm text-muted mb-10">
        <a href={METIS_RELEASES_URL} className="underline">
          Release assets and SHA256 checksums
        </a>{" "}
        (latest build on GitHub).
      </p>
      <ul className="space-y-8">
        {items.map((item) => (
          <li key={item.q}>
            <h2 className="font-semibold text-lg mb-2">{item.q}</h2>
            <p className="text-muted leading-relaxed">{item.a}</p>
          </li>
        ))}
      </ul>
      <p className="mt-12 text-sm text-muted">
        Still stuck?{" "}
        <a href={METIS_DISCUSSIONS_URL} className="underline">
          Open a discussion
        </a>{" "}
        — that is our main support path for {METIS_PRODUCT_NAME}.
      </p>
    </main>
  );
}
