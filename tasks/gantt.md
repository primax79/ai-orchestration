# Gantt — initiatives 06–09 (control plane)

Snapshot of 2026-10-17 11:15. Done tasks show their real day; open tasks start from now, with estimated durations (Kilo implementation plus architect review and live verification).

Each bar starts **after** the tasks it depends on. There are two kinds of dependency:

- the declared dependencies in each `plan.md`;
- the file lanes in `06-control-plane-safety/plan.md`: tasks that edit the same files never run in parallel.

Lanes:

| Lane | Files | Order |
| --- | --- | --- |
| Backend | `ai-orchestration-ui/backend` | 06.7 → 08.3 → 07.6 → 09.2 |
| Frontend | `ai-orchestration-ui/frontend` | 06.8 → 08.4 → 10.2 → 07.7 → 07.8 → 09.3 → 08.6 → 09.5 |
| VS Code | `vscode-ai-orchestration` | 06.9 → 08.5 → 07.9 → 09.6 |
| Runs | `orchestration_runs.py` | 07.2 → 07.3 → 07.4 → 07.10 → 09.4 |

The frontend order differs from the original plan: 08.4 comes before 07.7 because its backend (08.3) is ready first.

```mermaid
gantt
    title Control plane — initiatives 06–09
    dateFormat YYYY-MM-DD HH:mm
    axisFormat %d/%m %H:%M
    todayMarker stroke-width:3px,stroke:#d33

    section 06 Safety
    06.1 Lossless sync-index            :done, t061, 2026-10-16 21:00, 2h
    06.2 Doctor dry-run, no-clobber     :done, t062, 2026-10-16 21:00, 2h
    06.5 UI auth, async, watcher        :done, t065, 2026-10-16 21:00, 2h
    06.6 render-agents-md --diff        :done, t066, 2026-10-16 23:15, 1h
    06.3 Doctor plugin-aware            :done, t063, 2026-10-16 23:30, 1h
    06.10 Task-write lock               :done, t0610, 2026-10-16 23:45, 1h
    06.4 MCP real configs               :done, t064, 2026-10-17 00:30, 1h
    06.7 Backend preview/apply          :done, t067, 2026-10-17 10:15, 1h
    06.8 Frontend confirm and previews  :active, t068, 2026-10-17 11:00, 2h
    06.9 VS Code bridge parity          :t069, after t068, 2h

    section 07 Agent runs
    07.1 set-routing, TOML updater      :done, t071, 2026-10-16 21:00, 2h
    07.2 Runs A: registry, preview      :done, t072, 2026-10-17 00:00, 1h
    07.3 Runs B: supervisor, cancel     :done, t073, 2026-10-17 10:15, 1h
    07.4 Runs C: worktree, verify       :active, t074, 2026-10-17 10:45, 2h
    Q001 owner decision (permissions)   :milestone, q001, after t074, 0h
    07.5 Live capture, real CLIs        :t075, after t074 q001, 2h
    07.10 Supervisor files questions    :t0710, after t074, 1h
    07.6 Backend run endpoints          :t076, after t074 t083, 1h
    07.7 Run dialog and runs panel      :t077, after t076 t084, 2h
    07.8 Config tab editing             :t078, after t077, 1h
    07.9 VS Code run handlers           :t079, after t077 t078 t085, 1h

    section 08 Blocking questions
    08.1 Questions engine               :done, t081, 2026-10-17 00:00, 2h
    08.2 Skills use the format          :done, t082, 2026-10-17 10:45, 1h
    08.3 Backend question endpoints     :active, t083, 2026-10-17 11:00, 1h
    08.4 Decisions tab and badge        :t084, after t083 t068, 2h
    08.5 VS Code Decisions tree         :t085, after t084 t069, 1h
    08.6 Answer and resume run          :t086, after t084 t077 t0710 t093, 1h

    section 09 Inbox
    09.1 Inbox engine                   :active, t091, 2026-10-17 10:15, 2h
    09.2 Backend inbox and uploads      :t092, after t091 t076, 1h
    09.3 Inbox tab, paste screenshots   :t093, after t092 t078, 2h
    09.4 Agent triage mode              :t094, after t091 t0710, 2h
    09.5 Process with agent, review     :t095, after t093 t094 t086, 1h
    09.6 VS Code inbox                  :t096, after t093 t079, 1h

    section Release
    T012 effective after MCP restart    :milestone, t012, after t068, 0h
    Push and plugin update (owner OK)   :milestone, push, after t069 t079 t085 t096 t095 t075, 0h
```

## Reading notes

- **Critical path:** 07.4 → 07.6 → 07.7 → 07.8 → 09.3 → 09.5. The frontend lane is the bottleneck, because seven UI tasks share it.
- **Q001** blocks only 07.5, the live test with the real Claude. Every other task proceeds without it.
- **Push** waits for the end, as agreed; the owner approves it.
