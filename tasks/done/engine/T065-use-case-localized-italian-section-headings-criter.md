# T065 Intestazioni di sezione dei casi d'uso localizzate in italiano, opzione --criteria e titoli brevi con stop-word italiane

- id: T065
- title: Intestazioni di sezione dei casi d'uso localizzate in italiano, opzione --criteria e titoli brevi con stop-word italiane
- category: engine
- priority: P2
- priority-reason: I workspace in italiano necessitano di intestazioni UC localizzate, criteri di accettazione alla creazione e titoli brevi puliti
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261025-172456-use-cases-localized-section-headings/note.md
- paths: -
- handoff: Leggi tasks/engine/T065-use-case-localized-italian-section-headings-criter.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- short: Sezioni casi d'uso in italiano

## Goal

dave_agent scrive i task in italiano. I file dei casi d'uso (tasks/use-cases/UC*.md) ricevono intestazioni di sezione fisse in inglese da 'use-cases create' (Description & Business Value, Preconditions, Scenario / Interaction Steps, Automated Verification Command, Acceptance Criteria, AI Validation Log), e il motore le legge usando esattamente quei nomi (tasks_engine.py _extract_section intorno alla riga 6522; record-validation aggiunge in coda a '## AI Validation Log'). Tradurle rompe show/validate/record-validation. Soluzione temporanea in dave_agent: mantenere i file del motore e generare un documento in italiano con scripts/render_use_cases_it.py. Richiesta: accettare alias localizzati (ad es. Descrizione, Precondizioni, Scenario, Comando di verifica, Criteri di accettazione, Registro delle verifiche) durante il parsing, e un'impostazione di lingua per workspace per il template generato. Inoltre: create non ha un'opzione per i criteri di accettazione (usa sempre il generico '- [ ] Core flow works as expected.'), e il titolo breve derivato tronca a metà frase ('Tenere una cartella del').

## Steps

- [x] Supportare gli alias in italiano per le intestazioni, `--lang it`, `--criteria` e le stop-word italiane in `derive_short_title`.

## Verification

- [x] `pytest plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k test_t057_t061_t062_t063_t052_and_n064`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, owner: state `delivered` -> `verified` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, kilo: state `in progress` -> `delivered`
- 2026-10-25, kilo: state `open` -> `in progress`
