/**
 * Public URLs and copy — one place to change repo/support without hunting components.
 * Override via NEXT_PUBLIC_* in Vercel / .env.local for the site.
 */
export const METIS_PRODUCT_NAME = "Metis Command";

const repoBase =
  process.env.NEXT_PUBLIC_METIS_REPO_BASE?.replace(/\/$/, "") ||
  "https://github.com/om1o/Metis_Command";

export const METIS_RELEASES_URL = `${repoBase}/releases`;
export const METIS_LATEST_RELEASE_URL = `${repoBase}/releases/latest`;
export const METIS_DISCUSSIONS_URL = `${repoBase}/discussions`;
/** Single primary support path: GitHub Discussions (public, indexed, no inbox). */
export const METIS_SUPPORT_URL = METIS_DISCUSSIONS_URL;

export function metisVersion(): string {
  return process.env.METIS_VERSION || process.env.NEXT_PUBLIC_METIS_VERSION || "0.16.4";
}

export function downloadAssetHint(): string {
  return process.env.NEXT_PUBLIC_METIS_DOWNLOAD_LABEL || ".zip";
}
