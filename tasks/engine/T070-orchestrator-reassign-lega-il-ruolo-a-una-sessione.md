# T070 orchestrator reassign lega il ruolo a una sessione interattiva esistente

- id: T070
- title: orchestrator reassign lega il ruolo a una sessione interattiva esistente
- category: engine
- priority: P2
- priority-reason: Oggi crea una sessione headless fantasma e due salti di generazione (d4science_kb)
- next-up: no
- state: delivered
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261027-144357-orchestrator-reassign-cannot-hand-the-ro/note.md
- paths: ai-orch orchestrator reassign; ai-orch sessions register; UC028
- handoff: Read tasks/engine/T070-orchestrator-reassign-lega-il-ruolo-a-una-sessione.md, do the open steps, run the Verification, update the task and the registry.
- verify-by: d4science_kb
- short: Reassign su sessione attuale

## Goal

What (2026-10-27, workspace ~/works/d4science_kb): the owner declared the current interactive Claude Code session the orchestrator. Holder was gen 1, kilo, kind=interactive, status stale, turns 0.

## Steps

- [x] `ai-orch orchestrator reassign` accetta `--kind interactive --provider-session-id <uuid> [--session-id <name>]` e `--bind-current` (che legge l'ID del provider da `CLAUDE_SESSION_ID` / variabili d'ambiente esplicite o restituisce errore chiaro se assente), legando il ruolo alla sessione interattiva indicata con un solo salto di generazione, ritirando il titolare precedente tramite successione fenced e senza creare sessioni headless fantasma.
- [x] Senza questi flag il comportamento predefinito resta invariato (titolare headless con turno di handoff).
- [x] Se una sessione con quel `provider_session_id` è già registrata (es. tramite `sessions register`), viene riutilizzata preservando ID di registro, sottoscrizioni e metadati invece di crearne una nuova.
- [x] L'anteprima `--dry-run` espone la sessione target e il kind (`interactive` vs `headless`) e calcola `plan_hash` applicabile con `--expect-hash`.
- [x] Aggiunti test per successione da titolare gen 1 interattivo stale a gen 2 interattivo, riutilizzo di sessione già registrata, `--bind-current` via CLI e invarianza del percorso headless predefinito.

## Verification

- Test specifici T070 eseguiti con successo in `scripts/test_orchestration_orchestrator.py`:
  - `test_reassign_interactive_from_stale_interactive_holder`: titolare gen 1 interattivo (`kilo`) in stato `stale` -> `reassign --kind interactive --provider-session-id <uuid> --session-id d4science-kb-3d` -> gen 2 assegnata alla sessione interattiva indicata, `kind == "interactive"`, nessuna sessione headless presente in `sessions list`, sessione gen 1 ritirata con motivo `reassigned`.
  - `test_reassign_interactive_reuses_existing_registered_session`: sessione interattiva già registrata con `provider_session_id` viene riutilizzata in `reassign --kind interactive` mantenendo `session_id` e sottoscrizioni senza duplicati né sessioni headless.
  - `test_reassign_bind_current_cli`: `--bind-current` senza `CLAUDE_SESSION_ID` restituisce codice 2 con messaggio chiaro che richiede `--provider-session-id`; con `CLAUDE_SESSION_ID` impostato completa dry-run e apply in un singolo salto di generazione.
- Percorso predefinito headless verificato tramite `test_reassign_dry_run_shows_plan`, `test_reassign_stale_hash_refused`, `test_reassign_apply_succession_and_event` e `test_reassign_cli`.
- Suite completa `scripts/` eseguita con successo: `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/`.

## Log (newest first)

- 2026-10-27, kilo: state `open` -> `delivered` — reassign lega il ruolo orchestrator a una sessione interattiva esistente (--kind interactive / --bind-current) in un solo salto di generazione senza sessioni headless fantasma
