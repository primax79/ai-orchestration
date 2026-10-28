# T035 Chiusura in un solo comando, rifiuto più chiaro sullo stato derivato, chiusura massiva dei task verificati

- id: T035
- title: Chiusura in un solo comando, rifiuto più chiaro sullo stato derivato, chiusura massiva dei task verificati
- category: engine
- priority: P1
- priority-reason: Richiesto da tre sessioni (due come modifica prioritaria); oggi chiudere richiede quattro chiamate
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: inbox N008, N018, N025, N026
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Leggi tasks/tasks/T035-one-shot-close-clearer-derived-state-refusal-bulk.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- verify-by: gcube_audit
- short: Chiusura in un comando



## Goal

'tasks transition <id> done --verifier X [--reason R]' attraversa gli stati validi in una sola chiamata, esegue ogni guardia una volta e registra lo stesso motivo/verificatore a ogni passo (prima in dry-run). Un rifiuto su un nodo padre con stato derivato mostra lo stato derivato corrente e indica che si chiude quando si chiudono le sue foglie. Un comando massivo 'tasks close --verified [--dry-run]' chiude gli elementi verificati e l'indice conteggia 'finished, not archived'. Inoltre, dalla consultazione N035: auto-chiusura in un solo comando per i repository con un singolo operatore ('--self-verified', che registra 'done with a caveat: self-verified only' e una riga in PROGRESS); il comando di chiusura offre 'done with a caveat' con il relativo motivo (una sessione ha chiuso un incidente come semplice 'done' per mancanza di tale opzione); '--verifier' accetta un nome di sessione come valore di prima classe (es. 'gcube-atlas-83'). Ogni transizione scrive una riga datata (da, a, attore, verificatore, motivo) nel task stesso: PROGRESS.md per i task a cartella, una sezione '## Log' per i task a file singolo, così le validazioni sono registrate dove l'owner le legge (inbox N041, gcube_atlas).

## Steps

- [x] Far avanzare `tasks transition <id> done --verifier X [--reason R]` attraverso gli stati intermedi validi (`in progress -> delivered -> verified -> done`) da qualsiasi stato non terminale, applicando la guardia del verificatore indipendente e supportando `--dry-run` e `--owner-approved`.
- [x] Aggiungere il comando massivo `tasks close --verified [--dry-run] [--expect-plan-hash <hash>]` per visualizzare in anteprima e chiudere tutti i task nello stato `verified` con un unico hash del piano batch.
- [x] Normalizzare le grafie dello stato (`in-progress`, `In Progress`, `in_progress`, ecc.) in lettura in `normalize_state`, accettarle in `list`, `transition` e `close`, ed emettere un avviso con la grafia canonica in `validate` senza riscrivere i file in lettura.
- [x] Registrare una riga in `## Log` (o una voce in `PROGRESS.md` per i task a cartella) per ogni passo di transizione intermedio durante le esecuzioni di `close` e `transition`.
- [x] Aggiungere unit test in `test_tasks_engine.py` a copertura di tutti e quattro i punti riaperti.

## Verification

- [x] L'intera suite pytest passa (`563 passed`): `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/ plugins/architect-side/skills/task-pipeline/scripts/ plugins/shared/skills/orchestration-setup/scripts/`.
- [x] La verifica dal vivo su una copia temporanea `git init` di `tasks/` nella directory temporanea di sistema riproduce e valida tutti e quattro gli scenari di `gcube-audit` (`transition <id> done`, `close --verified`, `- state: in-progress` con trattino in `list`/`validate`/`close`, e righe `## Log` per ogni passo).

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Punti riaperti verificati in test_tasks_engine.py + controllo dal vivo su repo temporaneo; chiusura approvata dall'owner
- 2026-10-25, owner: state `delivered` -> `verified` — Punti riaperti verificati in test_tasks_engine.py + controllo dal vivo su repo temporaneo; chiusura approvata dall'owner
- 2026-10-25, kilo: state `in progress` -> `delivered` — Implementati l'avanzamento di transizione fino a done, la chiusura massiva close --verified, la normalizzazione della grafia dello stato e le voci di Log per ogni passo; 563 test passati
- 2026-10-25, kilo: state `open` -> `in progress`
- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzati e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzati e approvato dall'owner per la pulizia
- 2026-10-21, ai-coding-tools: state `in progress` -> `delivered` — Eseguito merge di 76391c4 + N041 registrazione su file singolo in ## Log; 12 nuovi unit test passano

## Riapertura 2026-10-25 (validazione del richiedente, gcube-audit)

Funziona: `tasks close <id> --verifier owner --reason r` da 'in progress' raggiunge done e scrive una riga di Log.
NON OK:
1. `tasks transition <id> done --verifier owner --reason r` viene rifiutato ("must pass through 'delivered' first" da in
   progress; da delivered l'elenco degli stati consentiti omette done). L'obiettivo prometteva l'avanzamento in una sola chiamata anche su `transition`.
2. `tasks close <id> --verified` (chiusura massiva degli elementi verificati) non esiste ("unrecognized arguments").
3. Un header `- state: in-progress` (con trattino, 6 task nel loro albero) non viene normalizzato: close e transition lo rifiutano,
   e list mostra canonical_state 'in-progress'. Normalizzare le grafie dello stato in lettura (e offrire una correzione in validate).
4. Il Log registra solo l'ultimo passo (verified -> done), non ciascuno dei passi intermedi.
Verificare di nuovo con il richiedente prima di chiudere.
