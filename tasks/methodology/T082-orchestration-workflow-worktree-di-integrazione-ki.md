# T082 orchestration-workflow: worktree di integrazione, kilo_cleanup, kilo_verify_worktree, verifica browser mirata

- id: T082
- title: orchestration-workflow: worktree di integrazione, kilo_cleanup, kilo_verify_worktree, verifica browser mirata
- category: methodology
- priority: P2
- priority-reason: Pattern provati su ricerca_auto e qui ogni giorno, non documentati nella skill (E.1, F.1, F.2, G.1)
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: lezioni di ricerca_auto 2026-10-17, analisi T078 (ai-orchestration/tasks/_reviews/2026-10-27-ricerca-auto-lessons-triage.md)
- paths: plugins/architect-side/skills/orchestration-workflow/SKILL.template.md
- handoff: Read tasks/methodology/T082-orchestration-workflow-worktree-di-integrazione-ki.md, do the open steps, run the Verification, update the task and the registry.
- short: Pattern di integrazione

## Goal

La skill orchestration-workflow (dal template) documenta: worktree di integrazione con merge --no-ff e test prima del ff su main, conflitti rimandati all'esecutore; kilo_cleanup e kilo_verify_worktree; verifica nel browser con valutazioni mirate e screenshot invece di snapshot giganti; cosa fare quando un permesso blocca.

## Steps

- [ ] Template aggiornato, rigenerazione con --check, skill legata di kilo-mcp rigenerata

## Verification

- --check pulito; sezioni presenti
