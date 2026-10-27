# T068 sync-index aggiorna le etichette delle iniziative quando cambia il titolo del piano

- id: T068
- title: sync-index aggiorna le etichette delle iniziative quando cambia il titolo del piano
- category: engine
- priority: P3
- priority-reason: Dopo la traduzione 65 etichette sono rimaste in inglese; sistemate a mano
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261027-122138-sync-index-keeps-stale-initiative-link-l/note.md
- paths: -
- handoff: Read tasks/engine/T068-sync-index-aggiorna-le-etichette-delle-iniziative.md, do the open steps, run the Verification, update the task and the registry.
- verify-by: ai-coding-tools
- short: Etichette iniziative aggiornate

## Goal

After translating plan titles (T036, 2026-10-27) sync-index reported 'already in sync' in ai-orchestration (15 rows) and ai-swissknife (50 rows) while the Initiatives/Done link labels still showed the old English titles; I rewrote them with a script. The T050 rule that keeps a hand-curated label treats any label shorter than the title as curated. Expected: a label equal to a PREVIOUS title of the plan is not curated and follows the current title, or a 'sync-index --refresh-labels' option.

## Steps

- [ ] Un'etichetta uguale a un titolo precedente del piano (dalla storia git o dal titolo registrato all'ultima sync) non è curata a mano e segue il titolo attuale; in alternativa un'opzione sync-index --refresh-labels

## Verification

- Test: piano rinominato, l'etichetta nell'indice si aggiorna; un'etichetta scritta a mano diversa da ogni titolo passato resta
