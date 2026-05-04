import Link from "next/link";
import { METIS_PRODUCT_NAME, METIS_DISCUSSIONS_URL, METIS_RELEASES_URL } from "@/lib/brand";

export const metadata = {
  title: `Support — ${METIS_PRODUCT_NAME}`,
  description: "Get help with Metis Command: one place to ask questions.",
};

export default function SupportPage() {
  return (
    <main className="min-h-screen px-6 py-16 max-w-2xl mx-auto text-left">
      <p className="text-sm text-muted font-mono mb-4">
        <Link href="/" className="hover:underline">
          ← Home
        </Link>
      </p>
      <h1 className="font-serif text-3xl md:text-4xl mb-6">Support</h1>
      <p className="text-muted mb-6">
        Stuck? We use <strong>one public channel</strong> so nothing gets lost
        in a private inbox.
      </p>
      <a
        href={METIS_DISCUSSIONS_URL}
        className="inline-block px-5 py-3 rounded-xl font-semibold bg-white/10 hover:bg-white/15 border border-white/10"
        rel="noopener noreferrer"
      >
        Ask on GitHub Discussions →
      </a>
      <p className="text-sm text-muted mt-8">
        Verifying downloads: checksums and assets live on the{" "}
        <a href={METIS_RELEASES_URL} className="underline hover:no-underline">
          Releases
        </a>{" "}
        page.
      </p>
    </main>
  );
}
