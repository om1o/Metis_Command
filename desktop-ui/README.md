# Metis Desktop UI

This is the Next/Tauri desktop surface for Metis. Use the repo-level dev script so port `3000` is always served from this canonical folder, not from a hidden `.claude/worktrees/*/desktop-ui` checkout.

## Run Locally

From the repo root:

```powershell
.\scripts\start_desktop_ui_dev.ps1
```

Open `http://127.0.0.1:3000/`.

Useful checks:

```powershell
# Verify port 3000 is free or already serving this folder.
.\scripts\start_desktop_ui_dev.ps1 -Check

# Install dependencies before starting.
.\scripts\start_desktop_ui_dev.ps1 -Install

# Stop a server on 3000 only if it is not this canonical desktop-ui folder.
.\scripts\start_desktop_ui_dev.ps1 -StopForeign
```

## Quality Gate

Run these before committing UI work:

```powershell
npm ci --no-audit --no-fund
npm run lint
npm run build
```

The GitHub `desktop UI lint + build` CI job runs the same checks with Node 20.

## Backend

The UI expects the Metis API bridge on `http://127.0.0.1:7331`. Start it with the normal launcher:

```powershell
python launch.py
```

If login or local-device auth fails, verify the bridge first:

```powershell
Invoke-WebRequest http://127.0.0.1:7331/health -UseBasicParsing
```
