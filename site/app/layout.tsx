import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Metis Command — local-first autonomous AI",
  description:
    "A Claude/Codex-style desktop AI that runs 100% on your hardware. 5-agent swarm, persistent memory, budget-gated autonomy.",
  openGraph: {
    title: "Metis Command",
    description: "Local-first autonomous AI operating system.",
    type: "website",
  },
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen relative">{children}</body>
    </html>
  );
}
