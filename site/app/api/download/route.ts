import { NextResponse } from "next/server";

export const runtime = "edge";

export async function GET() {
  const target =
    process.env.METIS_DOWNLOAD_URL ??
    "https://github.com/om1o/Metis_Command/releases/latest/download/metis-command-windows.zip";

  console.log(
    JSON.stringify({ event: "download_redirect", ts: Date.now(), target })
  );

  return NextResponse.redirect(target, 302);
}
