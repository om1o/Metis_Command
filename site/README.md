# Metis Command — marketing + download site

Next.js 15 + Tailwind CSS, deploys to Vercel in one command.

## Local dev

```powershell
cd site
npm install
npm run dev
# open http://localhost:3000
```

## Deploy to Vercel

```powershell
cd site
npx vercel login     # once
npx vercel --prod
```

Then in the Vercel project settings, set these environment variables:

| Name                 | Value                                                                       |
|----------------------|-----------------------------------------------------------------------------|
| `METIS_VERSION`      | e.g. `0.16.4`                                                                |
| `METIS_DOWNLOAD_URL` | `https://github.com/om1o/Metis_Command/releases/latest/download/metis-command-windows.zip` |
| `METIS_GITHUB`       | `https://github.com/om1o/Metis_Command`                                      |

Redeploy once the envs are set (`npx vercel --prod`).

## How the download works

`GET /api/download` does a 302 redirect to `METIS_DOWNLOAD_URL`. Stateless —
the site stores nothing and ships nothing.  The ZIP lives as a GitHub
Release asset.  Upload it once per version:

```powershell
cd ..
python scripts\package_metis.py --version 0.16.4
gh release create v0.16.4 dist\metis-command-windows.zip `
  --title "Metis Command v0.16.4" `
  --notes-file docs\CHANGELOG_V1_TO_V16.3.md
```
