# 02 - Modello formale dei task, macchina a stati e specifica di `orchestration.toml`

- **Short:** Modello formale dei task

> **Derived from specs:** [`../specs/task-and-state-model.md`](../../specs/task-and-state-model.md), [`../specs/orchestration-config-and-agents-md.md`](../../specs/orchestration-config-and-agents-md.md)

## Tasks

### 02.1 - Allineare `macroplan-authoring` e `orchestration-methodology` con la specifica unificata dei task e della verifica
- **Profile:** `deep-reasoning`
- **Status:** `done` (2026-10-15) · **Short:** Allineare skill metodologiche · **Use cases:** UC004, UC006, UC007, UC008
- **Focus files:** `tasks/specs/task-and-state-model.md`, `plugins/architect-side/skills/macroplan-authoring/SKILL.md`, `plugins/architect-side/skills/macroplan-authoring/references/template.md`, `plugins/architect-side/skills/orchestration-methodology/SKILL.template.md`
- **Steps:**
  1. Aggiornare `macroplan-authoring/SKILL.md` e `references/template.md` per includere la macchina a stati unificata (transizione `bounced`, campi opzionali `profile`, `verification-mode: self | cross-agent | panel | owner`, `verifier` dopo `handoff`).
  2. Aggiornare `orchestration-methodology/SKILL.template.md` ("Track task state as a path, not a label") affinché la sua tabella degli stati corrisponda a `tasks/specs/task-and-state-model.md` e documenti esplicitamente la verifica opzionale incrociata tra agenti / panel multi-engine su `delivered → verified`.
  3. Rigenerare le skill generiche (`scripts/regenerate_generic_skills.py`) e gli indici (`scripts/generate_skill_indices.py`).
- **Verification:**
  - `python3 scripts/regenerate_generic_skills.py && python3 scripts/generate_skill_indices.py` termina con codice 0.
- **Commit:** Singolo commit limitato a `02.1`.
