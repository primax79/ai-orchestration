# T015 Navbar labels wrap on narrow widths

- id: T015
- title: Navbar labels wrap on narrow widths
- category: micro
- priority: P3
- priority-reason: Cosmetic, but the VS Code Simple Browser and side panels are narrow by default
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: owner screenshot in the VS Code Simple Browser (2026-10-17)
- paths: ../ai-orchestration-ui/frontend/src/components/Navbar.tsx
- handoff: Read tasks/micro/T015-navbar-narrow-width.md and fix it.

## Goal

At widths below about 1100 px, the navbar items ("Install Skills & MCP", "Environment Doctor", "Orchestrator Config") wrap onto two or three lines, and the workspace chip is clipped. The navbar should stay on one line: short labels or icon-only items with tooltips below a breakpoint, and a horizontal scroll or overflow menu as the last resort.

## Steps

1. Add `white-space: nowrap` to the items and short labels ("Install", "Doctor", "Config") below 1100 px.
2. Use icon-only items with `title` tooltips below 760 px.
3. Keep the badges (Decisions count, active runs) visible in every mode.

## Verification

With the Playwright MCP at 1400, 1000 and 700 px wide, the navbar is one line high, no label wraps, and the badges are visible.
