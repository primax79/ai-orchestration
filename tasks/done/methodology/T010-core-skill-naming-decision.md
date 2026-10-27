# T010 Decisione sulla ridenominazione delle skill principali (tassonomia `docs/06` rispetto ai nomi attuali)

- id: T010
- title: Decisione sulla ridenominazione delle skill principali (tassonomia docs/06 rispetto ai nomi attuali)
- category: methodology
- priority: P2
- priority-reason: Necessaria decisione dell'owner se rinominare le skill principali (ad es. macroplan-authoring -> task-pipeline) prima del commit o rimandare per evitare modifiche invasive
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: tasks/_reviews/2026-10-15-coherence-review-from-claude.md (F5), docs/06-naming-taxonomy-and-coherence.md
- paths: docs/06-naming-taxonomy-and-coherence.md, plugins/, ../kilo-mcp/bindings/
- handoff: Leggere docs/06-naming-taxonomy-and-coherence.md e tasks/methodology/T010-core-skill-naming-decision.md, registrare la decisione dell'owner se eseguire o rimandare la ridenominazione delle skill principali e aggiornare il registro.
- verifier: owner
- short: Decisione rinomina skill

## Goal

Decidere se eseguire le ridenominazioni delle skill principali proposte in `docs/06-naming-taxonomy-and-coherence.md` §2.1 (`macroplan-authoring` → `task-pipeline`, `interactive-role-setup` → `orchestration-setup`, `delegation-roi-analysis` → `orchestration-metrics`, `task-delegation` → `task-worktree-ops`, `headless-executor-contract` → `executor-contract`) prima del commit, oppure rimandarle mantenendo i nomi attuali. (Nota: l'allineamento del prefisso `kilo-mcp-*` in `../kilo-mcp` §2.2 è già applicato).

## Steps

1. Confermare con l'owner se eseguire ora le ridenominazioni delle skill principali di `docs/06` §2.1 o se rimandarle.
2. Se rimandate: contrassegnare il §2.1 in `docs/06-naming-taxonomy-and-coherence.md` come rimandato/futuro e chiudere questo task.
3. Se approvate: rinominare le directory delle skill, i campi `name` del frontmatter, `skill-requirements.json`, `regenerate_generic_skills.py` e le mappature in `../kilo-mcp/scripts/regenerate_bound_skills.py`, quindi rigenerare e verificare.

## Verification

- `./bin/ai-orch config validate --plugin-dir ./plugins/architect-side --plugin-dir ./plugins/executor-side --plugin-dir ./plugins/shared` termina con codice 0.
- `python3 ../kilo-mcp/scripts/regenerate_bound_skills.py --check` termina con codice 0.
