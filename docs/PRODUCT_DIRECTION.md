# Metis Product Direction

## Positioning

Metis is a desktop-first automation operator.

Platform decision:
- Desktop first.

MVP surface decision:
- Browser control first.

Category language:
- Operator OS is the long-term category.
- The first implementation target is narrower than an OS.

## Current MVP

The current MVP is:
- manager
- browser cockpit
- safe mode and per-job auto mode
- automation board
- inbox with real event history
- manager policies for services and limits

The first release claim is:
`a local manager that can control a browser reliably and operate on your machine`

## Product Rules

- Safe mode is default.
- Auto mode is allowed per job only.
- Browser sessions are manager-owned execution surfaces.
- Local auth, local files, local browser runtime, and desktop shell reliability are first-class.
- Inbox and audit history are product truth sources.

## Not Current Priorities

Do not prioritize these unless directly required by the browser MVP:
- chat-first product work
- code workspace work
- plugin-store-first work
- image, video, and voice expansion
- broad OS control beyond browser execution

## Design Direction

Visual direction:
- control room
- dense operator UI
- strong state colors
- visible browser-control aura/banner
- real-time status, approvals, and audit surfaces
