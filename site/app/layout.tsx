import type { Metadata } from "next";
import "./globals.css";
import { METIS_PRODUCT_NAME, metisVersion } from "@/lib/brand";

const v = metisVersion();

export const metadata: Metadata = {
  title: `${METIS_PRODUCT_NAME} v${v} — local-first AI workspace`,
  description:
    "Desktop AI workspace: local models (Ollama), memory, agents, and a localhost API. You control the machine.",
  openGraph: {
    title: `${METIS_PRODUCT_NAME} v${v}`,
    description: "Local-first AI workspace for Windows. FAQ & support on site.",
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
