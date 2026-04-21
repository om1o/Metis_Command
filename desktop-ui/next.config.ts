import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'export',
  // Recommended for Tauri integration to avoid image optimization API dependence
  images: { unoptimized: true }
};

export default nextConfig;
