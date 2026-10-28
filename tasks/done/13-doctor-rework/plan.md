# 13 - Rielaborazione del Doctor: rilievi reali, azionabili e risolvibili

- **Short:** Rielaborazione del Doctor

> **Derived from:** [`../env-doctor/notes/T016-report.md`](../../env-doctor/notes/T016-report.md), lo studio basato su evidenze di ogni rilievo del Doctor sulla macchina dell'owner (2026-10-17). Ciascun task seguente corrisponde alla proposta del report con il medesimo id; leggere prima la relativa sezione nel report. La corsia di `orchestration_env.py` segue l'ordine `13.1 → 13.3 → 13.4 → 13.5 → 13.6 → 13.7`. Le parti UI seguono la corsia frontend.
>
> **Decisioni dell'owner** emerse dal report sono registrate come domande Q002–Q005. 13.2 e 13.3 usano la risposta a Q003 (policy sui plugin) laddove rilevante.

## Tasks (One Task = One Commit)

## Closed

### 13.1 - P1-a: interrompere il ciclo "Resolve" a vuoto (no-op)

- **Status:** `done` (2026-10-18; claude; verificato e unito; T012 attivo dal riavvio del server kilo-mcp) · **Short:** Correzione ciclo Resolve · **Size:** S · **Repo:** `ai-orchestration/` + `ai-orchestration-ui/` · **Use cases:** UC012
- **Goal:**
  - ogni conflitto porta `fixable: true|false`;
  - la UI mostra il rosso e "Resolve…" solo quando il piano contiene azioni eseguibili;
  - un piano composto da soli suggerimenti disabilita Apply;
  - l'ambito di progetto non ripete i rilievi globali.

### 13.4 - P1-d: rilevare le copie obsolete dei plugin

- **Status:** `done` (2026-10-17; claude; unito in main) · **Short:** Rilevamento plugin obsoleti · **Size:** S/M
- **Goal:** Segnalare le copie dei plugin Claude rimaste indietro rispetto alla propria sorgente, indicando la distanza in commit e la stringa di versione invariata.

### 13.6 - P2-b + P2-c: vista effettiva di Kilo; l'installazione rispetta i plugin e la policy

- **Status:** `done` (2026-10-21; Verificato da d4science-python-library-2e) · **Short:** Vista effettiva di Kilo · **Size:** M
- **Goal:**
  - una vista di Kilo che copre ogni cartella letta da Kilo (incluse `~/.claude/skills` e `~/.config/kilo/skills`);
  - `install-skills` salta le skill fornite da un plugin o che la policy sui conflitti rimuoverebbe, così installazione e risoluzione non si annullano più a vicenda.

### 13.2 - P1-b: modello di gravità, raggruppamento tra assistenti, presa d'atto persistente

- **Status:** `done with a caveat: validated by the architect, no user yet` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Gravità e presa d'atto · **Size:** M
- **Goal:**
  - quattro livelli di gravità;
  - rilievi raggruppati attraverso assistenti e ambiti;
  - un archivio delle prese d'atto indicizzato sugli hash del contenuto, così un rilievo si ripresenta quando una copia cambia;
  - le skill non gestite di terze parti sono informative, non ambra.

### 13.3 - P1-c: risoluzione più intelligente dei duplicati

- **Status:** `done with a caveat: validated by the architect, no user yet` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Risoluzione dei duplicati · **Size:** M
- **Goal:** Prima di emettere un avviso, confrontare con le versioni dei plugin in cache, il frontmatter normalizzato e la cronologia git dei repository sorgente. I duplicati che sono solo più vecchi o ri-serializzati diventano risolvibili automaticamente (5 sugli 11 presenti su questa macchina).

### 13.5 - P2-a + P2-d: classificazione consapevole della cronologia per le installazioni legacy (`outdated-legacy` + "Update")

- **Status:** `done with a caveat: validated by the architect, no user yet` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Classificazione installazioni legacy · **Size:** M
- **Goal:** Le copie antecedenti alle ricevute che corrispondono a un commit sorgente precedente sono classificate come `outdated-legacy`, non `foreign`, e la UI offre "Update". Vengono gestiti anche i duplicati composti da sole copie standalone.

### 13.7 - P3-a..d: azioni per file spuri e MCP ridondanti, idempotenza di `register-mcp`, agenti nel Doctor, generalizzazione dei conflitti di attivazione

- **Status:** `done with a caveat: validated by the architect, no user yet` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** File spuri e MCP · **Size:** M
- **Goal:** Report §P3.
