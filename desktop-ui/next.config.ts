import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'export',
  // Recommended for Tauri integration to avoid image optimization API dependence
  images: { unoptimized: true },
  // Next.js 16 blocks dev-server resources (fonts, HMR, scripts) from any
  // host other than the one Next prints at startup. We bind to all of:
  // 127.0.0.1, localhost, and the LAN IP for the desktop / Tauri shell.
  // Without this, the page loads but fonts + HMR are blocked, which
  // shows as a black/blank screen.
  allowedDevOrigins: ['127.0.0.1', 'localhost', '10.0.0.147'],
};

export default nextConfig;
