# Brand and support (internal)

## Product name

Use **Metis Command** everywhere (site, installer `AppName`, Streamlit chrome, docs).

## Version

Single source: `metis_version.py` → `METIS_VERSION`.

Also bump:

- `pyproject.toml` `[project].version`
- Site build: `METIS_VERSION` or `NEXT_PUBLIC_METIS_VERSION` (Next.js)
- Inno: `build_installer.ps1` reads `metis_version.py` and passes `/DMyAppVersion=...`

## Support (one path)

**GitHub Discussions** on the main repo — same URL in:

- `site/lib/brand.ts` → `NEXT_PUBLIC_METIS_REPO_BASE` (default `https://github.com/om1o/Metis_Command`)
- `metis_version.py` → `METIS_SUPPORT_URL` (override with env for forks)

Do not split between email, Discord, and Discussions for the same tier of help; add a second path only if you staff it.

## Marketing site

Optional: set `METIS_MARKETING_SITE` in the Metis app environment so **About** shows a link to your public site.

## Logo

Site: `site/public/logo.png`. Installer: Inno default icon unless you add a branded `.ico` and set `SetupIconFile`.
