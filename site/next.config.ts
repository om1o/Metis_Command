import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  env: {
    METIS_VERSION: process.env.METIS_VERSION ?? "0.16.4",
    METIS_DOWNLOAD_URL:
      process.env.METIS_DOWNLOAD_URL ??
      "https://github.com/om1o/Metis_Command/releases/latest/download/metis-command-windows.zip",
    METIS_GITHUB: "https://github.com/om1o/Metis_Command",
  },
};

export default nextConfig;
