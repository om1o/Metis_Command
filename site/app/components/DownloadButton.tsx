"use client";

import { Download } from "lucide-react";
import { useState } from "react";

export default function DownloadButton() {
  const [pending, setPending] = useState(false);
  return (
    <a
      href="/api/download"
      onClick={() => setPending(true)}
      className="group inline-flex items-center gap-3 px-6 py-3 rounded-full font-semibold text-bg0 shadow-glow transition hover:-translate-y-0.5 hover:shadow-card"
      style={{
        background:
          "linear-gradient(135deg,#E8A446 0%,#FF6B9D 45%,#8B6CFF 100%)",
      }}
    >
      <Download className="w-4 h-4" />
      {pending ? "Preparing download…" : "Download for Windows"}
      <span className="opacity-70 text-xs font-mono">.zip</span>
    </a>
  );
}
