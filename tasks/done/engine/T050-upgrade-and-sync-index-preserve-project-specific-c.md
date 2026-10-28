# T050 upgrade e sync-index preservano i contenuti specifici del progetto; campi di estensione per progetto

- id: T050
- title: upgrade e sync-index preservano i contenuti specifici del progetto; campi di estensione per progetto
- category: engine
- priority: P1
- priority-reason: upgrade/sync-index distruggono le regole del progetto e le colonne del registro; porting_liferay non può adottare il motore attuale e avvisa le proprie sessioni di non eseguirli
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N049 (porting_liferay, T124 there)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py, plugins/architect-side/skills/task-pipeline/SKILL.md
- handoff: Leggi tasks/engine/T050-upgrade-and-sync-index-preserve-project-specific-c.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: porting_liferay
- verify-by: porting_liferay
- use-cases: UC014
- short: Upgrade non distruttivo

## Goal

upgrade non sostituisce mai un file tasks/AGENTS.md esistente: aggiunge o aggiorna un blocco gestito tra marcatori e mantiene tutto il resto; sync-index riscrive solo le proprie sezioni generate, mantiene le colonne aggiuntive definite da un progetto (es. Owner) e l'ordine di Next up del progetto salvo diversa richiesta, e non trasforma mai i file accessori in righe di task; upgrade termina con codice 0 in caso di successo mostrando un piano chiaro; una configurazione per progetto ([tasks] extension_fields nel file orchestration.toml del progetto, o una dichiarazione in tasks/AGENTS.md) permette a validate di accettare campi header specifici del progetto come 'area'. Verificato su una copia temporanea di ~/works/gcube/porting_liferay/tasks (in sola lettura sull'originale): il diff preserva le loro regole e colonne.

## Steps

- [x] `tasks/AGENTS.md` non distruttivo in `upgrade`: racchiudere la convenzione gestita tra `<!-- ai-orch:managed begin -->` ... `<!-- ai-orch:managed end -->`, preservando byte per byte tutto il contenuto specifico del progetto esterno ai marcatori; supportare `--dry-run`/`--preview` e `--apply --expect-hash`.
- [x] `sync-index` non distruttivo: preservare le colonne aggiuntive nelle tabelle (come `Owner` nelle tabelle di categoria), preservare l'ordine esistente delle righe di `Next up` e delle categorie a meno che non venga passato `--reorder`, preservare il formato semplice della cella `Id` quando l'indice esistente lo usa, e ignorare i file accessori (`T###-*.md`) privi di blocco header del task.
- [x] Campi di estensione dell'header per progetto e codice di uscita di `upgrade`: consentire `[tasks] extension_fields = ["area", ...]` in `orchestration.toml` o in blocchi `toml` delimitati in `tasks/AGENTS.md`; `upgrade` termina con `0` quando il proprio lavoro ha successo e segnala i problemi di validazione preesistenti come avvisi.
- [x] Aggiungere test di regressione in `test_tasks_engine.py` e verificare su una copia temporanea di `~/works/gcube/porting_liferay/tasks`.
- [x] Correzioni post-bounce (2026-10-25): analizzare le dichiarazioni in prosa `Extra header fields:` in `tasks/AGENTS.md` e documentare le forme accettate nel blocco gestito; omettere da `Decisions waiting` i task bloccati/in attesa con solo decider ma senza una domanda esplicita; rispettare gli header `short:` e le etichette brevi curate a mano come `T### (short)` nelle tabelle di categoria; aggiungere riepiloghi dei diff per sezione delle tabelle/Next-up nelle anteprime di `upgrade`/`sync-index` e stampare `[ok] already in sync, nothing written` quando `sync-index --apply` non produce modifiche.

## Verification

- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k "test_t050"`
- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/ plugins/architect-side/skills/task-pipeline/scripts/ plugins/shared/skills/orchestration-setup/scripts/`
- Verifica dal vivo su una copia temporanea di `~/works/gcube/porting_liferay/tasks` (anteprima di `upgrade` + `--apply --expect-plan-hash`, `sync-index --apply`, `validate`): 0 avvisi `unknown header field(s): area`, nessuna riga `T038` in `Decisions waiting`, `T154 (client/model compatibility check)` preservato nella tabella di categoria, riepilogo dell'anteprima per sezione stampato, e `[ok] already in sync, nothing written` al successivo `sync-index --apply`.
- `python3 plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py validate --tasks-dir tasks`
- `python3 plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py sync-index --tasks-dir tasks --check`

## Respinto 2026-10-25 (validazione del richiedente, porting-liferay-8c, su una copia usa e getta del loro albero)

OK: l'anteprima non scrive nulla e l'hash del piano funziona; regole del progetto in tasks/AGENTS.md intatte, blocco gestito solo
accodato; colonna Owner e formato Id mantenuti; nessuna riga da file accessori; nessuna riga persa; sync-index dopo upgrade è idempotente.
NON OK:
1. **`area` dichiarato in prosa non viene riconosciuto.** Il loro tasks/AGENTS.md dice ``**Extra header fields: `area`** (free-text
   topic label)``; validate avvisa 100 volte "unknown header field(s): area". get_project_extension_fields dichiara (nel commento) di
   leggere "Extra header fields: `area`" ma riconosce solo `extension_fields = [...]`. Un blocco delimitato ```toml [tasks]
   extension_fields = ["area"]``` funziona. Analizzare la forma in prosa (con o senza grassetto), oppure rimuovere l'affermazione e documentare
   la forma delimitata nel blocco gestito.
2. **Riga Decisions spuria.** Dopo upgrade la tabella delle decisioni ottiene `| T038 | P2 | Alfredo | Alfredo | - |` (il nome del decider
   nella colonna "Question (exact)") per un task bloccato con `decider: Alfredo` e nessuna domanda. Atteso: nessuna
   riga, oppure il testo della domanda estratto dal corpo.
3. **`short` ignorato nelle tabelle di categoria.** Le righe che usavano l'etichetta breve (es. T154 `- short: client/model
   compatibility check`) diventano titoli completi; rispettare `short` (come altrove: `ID (short)` o una colonna short), oppure segnalarlo
   nel piano.
4. Minore: l'anteprima riassume solo "+94/-67 lines"; fornire un riepilogo per sezione (righe aggiunte/rimosse/modificate per
   tabella, modifiche a Next up). sync-index stampa "[ok] updated" anche quando non è cambiato nulla.
Consegna: `~/.local/bin/ai-orch` risolve una copia più vecchia del plugin installato priva di --apply/--expect-plan-hash, quindi T054
e T050 non sono attivi per i progetti che usano il launcher finché i plugin non vengono rilasciati e reinstallati.
Ricontattare porting_liferay una volta corretto; rieseguiranno il test sulla copia.

### Corretto 2026-10-25 (kilo)

1. **Dichiarazione in prosa dei campi di estensione:** `get_project_extension_fields` ora analizza le dichiarazioni in prosa/elenchi puntati ``Extra header fields: `area` `` (con o senza grassetto, uno o più nomi di campo tra backtick separati da virgole o `and`/`or`), oltre ai blocchi delimitati `toml` e a `orchestration.toml`. Documentate tutte le forme accettate in `MANAGED_TASKS_AGENTS_BLOCK` e `SKILL.md`.
2. **Nessuna riga Decisions spuria:** `_extract_task_decision_question` richiede una domanda esplicita (nella forma `<who>: <question>` in `decider` dove la domanda differisce dal nome del decider, oppure un `Question:` / `## Question(s)` esplicito nel corpo, o un file di domanda `Q###` aperto) e non ripiega mai sull'inserimento del nome del decider in `Question (exact)`. I task bloccati/in attesa con `decider: Alfredo` e senza domanda (come `T038`) non producono alcuna riga Decisions.
3. **Titoli brevi nelle tabelle di categoria:** `_format_index_id_cell` rispetta gli header `short:` espliciti e le etichette brevi curate a mano nelle celle `[label](path)` formattando la cella `Id` come `T### (short)` (es. `T154 (client/model compatibility check)`) in modo uniforme tra `Next up`, `Tasks by category` e `Done`, mantenendo gli ID semplici `T###` per i task privi di `short:` negli indici a ID semplice.
4. **Riepilogo del piano per sezione e messaggio di nessuna modifica:** `summarize_index_changes` riporta le righe aggiunte/rimosse/modificate per sezione e per tabella di categoria più le variazioni di appartenenza a `Next up` nelle anteprime di `upgrade` e `sync-index`; `sync-index --apply` stampa `[ok] already in sync, nothing written` quando non sono necessarie modifiche.

## Log (newest first)

- 2026-10-25, porting_liferay: state `verified` -> `done`
- 2026-10-25, porting_liferay: state `delivered` -> `verified`
- 2026-10-25, kilo: state `bounced` -> `delivered` — KO3 corretto: formato della cella Id mantenuto per tabella; short va nel testo del link Task nelle tabelle a id semplice
- 2026-10-25, porting-liferay-8c: state `delivered` -> `bounced` — Ricontrollo NON OK solo su KO3: etichetta short inserita nella cella Id invece che nel testo del link Task (57 celle Id modificate)
- 2026-10-25, kilo: state `bounced` -> `delivered` — Corretti tutti i 4 punti del bounce, aggiunti 5 test di regressione, verificato su copia temporanea di porting_liferay/tasks
- 2026-10-25, porting-liferay-8c: state `delivered` -> `bounced` — Validazione del richiedente NON OK: extension_fields in prosa non analizzato, riga Decisions spuria, titoli brevi persi nelle tabelle di categoria (dettagli nel task)

## Ricontrollo 2026-10-25 (porting-liferay-8c, architect-side 0.7.2): resta un punto

OK: l'anteprima non scrive nulla, riepilogo per sezione, 0 righe rimosse da AGENTS.md, KO1 (0 avvisi su area), KO2 (nessuna riga Decisions per T038),
messaggio "already in sync", nessuna riga persa.
NON OK, KO3: l'etichetta breve è finita nella cella **Id** (`| T154 (client/model compatibility check) | … | [full title](…)`),
modificando 57 celle Id e rompendo ricerche come `grep '^| T154 |'`. La convenzione del progetto prevede un Id semplice e l'etichetta
breve come **testo del link Task** (`| T154 | P0 | [client/model compatibility check](social-sg4/T154-….md) |`). Correzione: mantenere
la cella Id esattamente nel formato già usato dalla tabella (`T###` semplice in questo caso), e inserire `short`, quando presente, nel
testo del link Task; non modificare mai il formato esistente della cella Id. (La specifica precedente suggeriva la forma nella cella Id; era sbagliato
per le tabelle la cui colonna Id è semplice.)

### Corretto 2026-10-25 (kilo), KO3

- `_table_uses_bare_id_format` determina per ciascuna tabella il formato della cella `Id` a partire dalle righe esistenti della tabella (ripiegando su `_index_uses_bare_id_format` a livello di indice per le tabelle vuote o appena create, e su `T### (short)` quando l'indice non ha righe `T###`).
- Quando una tabella usa ID semplici `T###` (`prefer_bare=True`), `_format_index_id_cell` emette sempre `T###` semplice (anche quando `short:` è presente), e `_format_index_task_cell` inserisce `short` (o un'etichetta breve esistente curata a mano che supera `_extract_hand_curated_short_label`) nel testo del link `Task` `[short](rel_path)`, mantenendo altrimenti il titolo completo.
- Quando una tabella usa ID `T### (short)` (`prefer_bare=False`), `_format_index_id_cell` mantiene `T### (short)` nella cella `Id` e `_format_index_task_cell` mantiene `[title](rel_path)` come testo del link `Task`.
