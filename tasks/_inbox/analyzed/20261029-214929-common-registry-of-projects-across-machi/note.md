# N079 Common registry of projects across machines

- id: N079
- title: Common registry of projects across machines
- kind: feature
- status: processed
- created: 2026-10-29T21:49:29.788924+00:00
- author: claude (ricerca_auto architect session)
- about: /Users/Alfredo/works/ricerca_auto
- produced: specs/multi-machine-development-architecture.md (+ review 2026-10-29), initiative 19, UC038-UC040, T087
- processed-by: claude (ai-coding-tools session, 2026-10-29)

## What

A common registry of projects shared across the owner's machines is needed. `ai-orch workspace` (orchestration_registry.py, SQLite under the global config dir `broker/registry.sqlite`) is per machine, and projects are only there if someone registers them explicitly: ricerca_auto is not registered on the Mac.

## Context

The owner is migrating all workspaces from the Mac to the dev server alf_ubuntu (`~/works/MIGRATION_REGISTRY.json` + `render_registry.py` on both machines, a separate hand-maintained registry) and wants local orchestrators on the server plus one orchestrator on the Mac, with tasks annotated with the machine that has them in charge.

## Expected

- One registry of projects (identity, paths per machine, which machine is primary for development, convention/schema version, orchestration status, remote/backup policy), readable and updatable from both machines; the per-machine SQLite becomes a cache or a view of it.
- Automatic discovery/registration proposal for projects that contain a `tasks/` tree or an AGENTS.md rendered by ai-orchestration.
- Reconcile or absorb the existing `~/works/MIGRATION_REGISTRY.json` instead of keeping two registries.

---
- Author: claude (ricerca_auto architect session)
- Workspace: /Users/Alfredo/works/ricerca_auto
- ai-orch: 1.1.0 (2965604)
- Date: 2026-10-29 21:49:28 UTC
