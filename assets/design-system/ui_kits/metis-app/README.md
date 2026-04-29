# Metis App — UI Kit

A high-fidelity, click-thru recreation of the Metis operator workspace.

## What's here

- `index.html` — interactive demo: sidebar nav, mission chat, mission timeline, artifacts library, settings.
- `components/AppShell.jsx` — outer layout (sidebar + topbar + content).
- `components/Sidebar.jsx` — primary nav, mission list, footer status.
- `components/Topbar.jsx` — search + run status + user.
- `components/Chat.jsx` — chat thread, composer, streaming/thinking states.
- `components/MissionTimeline.jsx` — workout-plan-style mission stepper with logs.
- `components/ArtifactsView.jsx` — grid of artifact cards with filter chips.
- `components/Primitives.jsx` — Button, Card, Chip, Input, Icon (Lucide).

## What this is **not**

A working agent system. All data is fixtures; "running" missions are scripted timers. The point is **visual + interaction fidelity** for designers.
