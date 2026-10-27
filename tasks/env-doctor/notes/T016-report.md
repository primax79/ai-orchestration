# Report T016: le segnalazioni persistenti del Doctor sono reali?

- Data: 2026-10-17. Macchina: Mac dell'owner, home reale, in sola lettura (solo esecuzioni `env status` e `--dry-run`).
- Codice esaminato: `scripts/orchestration_env.py` (2694 righe al momento dello studio), `../ai-orchestration-ui/frontend/src/components/EnvironmentDoctor.tsx`, `../ai-orchestration-ui/frontend/src/components/ConfirmDialog.tsx`, `../ai-orchestration-ui/frontend/src/components/SkillInstaller.tsx`, `../ai-orchestration-ui/backend/server.py`.
- Specifica: `tasks/specs/control-plane-safety.md` (§0 A4–A6, §1 E3–E7, §2.1).

## In sintesi

Le segnalazioni che "non si risolvono mai" ricadono in tre gruppi:

1. **Problemi reali che il Doctor non può risolvere.** Vengono mostrati come errori rossi risolvibili con un pulsante "Resolve…". Il piano dietro quel pulsante contiene solo elementi `ADVISE`, quindi applicarlo non fa nulla. Subito dopo ricompaiono gli stessi banner rossi. Questa è la causa principale della segnalazione dell'owner: **tutti i 12 conflitti di Claude (24 banner, poiché lo scope di progetto ripete quelli globali) restano bloccati in un ciclo no-op.**
2. **Classificazioni errate.** 17 skill sono etichettate come `foreign`. 14 di esse sono copie meno recenti del nostro stesso catalogo (corrispondenza esatta del blob nella cronologia git del repository sorgente) e 2 differiscono solo per la quotatura YAML. 38 skill `unmanaged` (legittime skill di terze parti e del toolkit) ricevono lo stesso badge ambra di un disallineamento reale.
3. **Controlli mancanti.** Il Doctor non rileva i problemi effettivi:
   - le copie dei plugin di Claude sono obsolete rispetto ai repository sorgente (plugin ai-orchestration indietro di 69 commit, plugin kilo-mcp indietro di 7) mentre le rispettive stringhe di versione sono invariate;
   - anche Kilo carica `~/.claude/skills` e `~/.config/kilo/skills`, producendo 14 duplicati reali tra directory diverse e un conflitto di trigger che il Doctor non mostra mai.

Cosa deve cambiare: la logica di risoluzione, le regole di classificazione **e** la presentazione nella UI. Nulla qui va "bene così com'è".

## Tabella di riepilogo

I conteggi si riferiscono a `--workspace /Users/Alfredo/works/ai-coding-tools` salvo diversa indicazione (AO = `--workspace .../ai-orchestration`).

| # | Tipo (come mostrato) | Conteggio | Verdetto | Causa radice | Modifica proposta | Dimensione |
|---|---|---|---|---|---|---|
| 1 | `duplicate-name`, standalone vs plugin di Claude (banner rosso + "Resolve…") | 11 (Claude globale), mostrati due volte (globale + progetto) = 22 banner | VERO (Claude carica davvero entrambe le copie). Presentato erroneamente come risolvibile | `resolve_conflicts` sposta nel cestino una copia standalone solo se è identica byte per byte, `up-to-date` o corrisponde all'hash del catalogo (`orchestration_env.py:1978-1982`). Tutte e 11 differiscono, quindi diventano `advise` (`:2002-2019`). L'applicazione esegue solo `conflict_items` (`:2081`), che è una no-op. La UI mostra comunque il rosso + "Resolve…" (`EnvironmentDoctor.tsx:317-358`) e Confirm resta abilitato | (a) Pulsante Resolve e colore rosso solo quando il piano ha ≥1 azione eseguibile. (b) Uguaglianza più intelligente: normalizzata sul frontmatter, qualsiasi versione in cache dello stesso plugin, cronologia git del catalogo. Questo rende 5 su 11 risolvibili automaticamente. (c) Gli elementi di solo avviso ricevono "acknowledge" | S + M |
| 2 | `trigger-conflict` `orchestration-workflow` + `kilo-mcp-orchestrator` (Claude) | 1, mostrato due volte | VERO MA NON RISOLVIBILE DAL DOCTOR | La policy `claude=bound` rimuove la skill generica, che esiste solo come plugin `architect-side@ai-orchestration`, quindi il piano dice ADVISE "disable plugin" (`:1926-1943`). Ciò eliminerebbe anche 5 skill non correlate. La UI lo mostra in rosso con "Resolve…" perché tra le voci c'è una `kilo-mcp-orchestrator` standalone (`EnvironmentDoctor.tsx:284`) | Severità info + testo di avviso proporzionato + acknowledge. A lungo termine: la descrizione della skill generica rimanda alla skill associata quando sono entrambe presenti | S |
| 3 | stato `foreign` (badge ambra) | kilo 5, claude 7, codex 5 = 17 | Per lo più FALSO come "foreign": 14 sono versioni precedenti delle nostre skill, 2 differiscono solo per la quotatura YAML, 1 è obsoleta + quotatura | Regola A4 della specifica "nessuna ricevuta e nessuna corrispondenza hash → foreign" (`:436-454`). Nessuna delle 3 directory delle skill nella home ha un singolo `.ai-orch-source.json`, perché sono state installate prima che esistessero le ricevute o da altri strumenti. Non possono essere ripulite dalla UI: `install-skills` fa SKIP di `foreign` a meno di `--overwrite` (`:1602-1610`), e `SkillInstaller.tsx:39,48` non passa mai `overwrite` | Nuovo stato `outdated-legacy` (confronto con la cronologia git del file di catalogo, o uguaglianza normalizzata sul frontmatter). Un'azione per riga "Update (overwrite)" con anteprima del diff | M |
| 4 | stato `unmanaged` (badge ambra) | kilo 21+2, claude 13+2 = 38 | FALSO come avviso | Il catalogo copre solo `ai-orchestration`, `kilo-mcp`, `claude-mcp` (`:339`). Ogni altra skill è `unmanaged`, e la UI colora in ambra ogni stato diverso da up-to-date/plugin/obsolete (`EnvironmentDoctor.tsx:455-470`) | Badge grigio neutro "external", compresso di default, nessuna severità | S |
| 5 | Lo scope di progetto di Claude ripete i conflitti globali e le righe dei plugin | 12 banner + 34 righe plugin duplicate | FALSO (duplicazione di presentazione) | La vista di progetto è costruita come l'unione di standalone globali + plugin (`:1138-1149`, `:1192-1195`). La UI la renderizza come uno scope separato | Mostrare nello scope di progetto solo i conflitti che coinvolgono una voce a livello di progetto. Mostrare "inherited from global" su una sola riga | S |
| 6 | `duplicate-name` standalone di progetto vs standalone globale (solo AO) | 5 | VERO (copie scritte oggi alle 11:13Z in `ai-orchestration/.claude/skills`, non tracciate in git) ma manca il percorso di risoluzione | `resolve_conflicts` ha rami solo per standalone+plugin e solo plugin (`:1949`, `:2021`). I duplicati solo standalone non producono **alcun elemento nel piano**, eppure la UI li mostra in rosso con "Resolve…" | Aggiungere un ramo: identiche → cestinare la copia di progetto (o seguire una regola configurabile); diverse → avvisare con diff | S |
| 7 | `stray` `~/.codex/config.json` (banner ambra) | 1 | VERO MA NON RISOLVIBILE DAL DOCTOR | Scritto il 2026-10-15 alle 14:21 dal vecchio `register-mcp` (spec E3). Codex legge `config.toml`. Secondo la spec §2.1 viene segnalato "senza eliminarlo" e non esiste alcuna azione | Azione "Move to trash" con anteprima, mostrando se ciascun server presente al suo interno è già in `config.toml` | S |
| 8 | MCP `Overrides:` (ambra) su `playwright` di Kilo | 1 | VERO ma innocuo (definizioni identiche) | `kilo.json` (scritto nello stesso secondo del #7) e `kilo.jsonc` definiscono entrambi `playwright` con lo stesso comando. `read_kilo_merged_mcps` segnala qualsiasi ridefinizione (`:793-799`) senza confrontare il contenuto | Confrontare le configurazioni: "redundant (identical)" = info, "conflicting" = warning. Offrire la rimozione della voce da `kilo.json` | S |
| 9 | Agente `kilo-mcp-orchestrator-agent.md` `foreign` (Claude) | 1 (solo JSON, non renderizzato) | FALSO (adattamento deliberato per assistente) | La copia di Claude omette il frontmatter `mode`/`permission` specifico di Kilo. Lo sha grezzo differisce (`:457-522`). La UI non ha alcuna tabella degli agenti | Trasformazione dell'agente per assistente al momento dell'installazione + hash dell'output trasformato. Renderizzare gli agenti nella UI | M |
| 10 | (non segnalato) Copie dei plugin di Claude obsolete rispetto al sorgente | 2 plugin | CONTROLLO MANCANTE (problema VERO) | Le voci dei plugin ricevono sempre lo stato `plugin` (`:1136`) senza controllo di disallineamento. Cache del plugin `architect-side@ai-orchestration` = `30521e8a`, 69 commit indietro rispetto a HEAD. `architect-side@kilo-mcp` = `1a35cc0`, 7 indietro. Versioni in `plugin.json` invariate (0.3.0 / 0.2.2), quindi Claude non li aggiornerà. Conseguenza: "keep plugin copy" mantiene la copia **più vecchia** | Stato di disallineamento del plugin (`plugin-stale`) per i plugin il cui marketplace è un repository del catalogo. Avvisare "bump version and update plugin" | M |
| 11 | (non segnalato) Duplicati tra directory diverse in Kilo e conflitto di trigger in Kilo | 14 nomi dup + 1 trigger | CONTROLLO MANCANTE (problema VERO) | Kilo carica `~/.claude/skills/**`, `~/.agents/skills/**`, `~/.config/kilo/{skill,skills}`, `~/.kilo/{skill,skills}`. Il Doctor scansiona solo `~/.kilo/skills` (`:259-274`) | Vista effettiva di Kilo su tutte le radici lette da Kilo | M |
| 12 | (piano, non segnalazione) `install-skills` crea nuovi conflitti | 5 + 2 | VERO difetto di progettazione (ping-pong) | Il piano di installazione ignora la copertura dei plugin e la policy dei conflitti (`:1583-1619`) | Saltare i nomi forniti da un plugin abilitato e i nomi che la policy rimuoverebbe | S |
| 13 | (piano, non segnalazione) `register-mcp` non idempotente | 2 | VERO (minore) | Pianifica `cli` anche quando `current_state: registered`, con un comando di avvio diverso | No-op quando è già registrato con un comando equivalente. Altrimenti un elemento `replace` che mostri il vecchio e il nuovo comando | S |

## Evidenze

### 0. Comandi eseguiti

```sh
./bin/ai-orch env status --workspace /Users/Alfredo/works/ai-coding-tools --json      # rc=0
./bin/ai-orch env status --workspace /Users/Alfredo/works/ai-coding-tools/ai-orchestration --json   # rc=0
./bin/ai-orch env resolve-conflicts --dry-run --workspace /Users/Alfredo/works/ai-coding-tools      # rc=0
./bin/ai-orch env install-skills --dry-run --assistants all --scope global              # rc=0
./bin/ai-orch env register-mcp kilo-mcp --assistants all --scope global --dry-run [--json]   # rc=0
```

Inventario da `env status --json` (conteggi di `(origin, state)` in `skill_entries`):

```text
kilo   global  ~/.kilo/skills        unmanaged 21, up-to-date 7, foreign 5           structured: none
kilo   project ws/.kilo/skills       unmanaged 2                                       (AO: up-to-date 12)
claude global  ~/.claude/skills      unmanaged 13, foreign 7, up-to-date 1, plugin 33  structured: duplicate-name 11, trigger-conflict 1
claude project ws/.claude/skills     unmanaged 2, plugin 33 (repeated)                 structured: duplicate-name 11, trigger-conflict 1  (AO: 16 + 1)
codex  global  ~/.codex/skills       up-to-date 7, foreign 5                           structured: none
codex  project                       0                                                 (AO: up-to-date 12)
stray: ['/Users/Alfredo/.codex/config.json']
MCP: kilo global {codex-mcp, playwright(overrides kilo.json), redmine, sequentialthinking};
     claude global {codex, codex-mcp, kilo-mcp, playwright, redmine}; codex global {kilo-mcp, playwright, vscode-dap}
```

Non esistono voci `modified-or-outdated` né `obsolete-renamed` su questa macchina. Controllo delle ricevute:

```text
$ ls ~/.kilo/skills/*/.ai-orch-source.json ~/.claude/skills/*/.ai-orch-source.json ~/.codex/skills/*/.ai-orch-source.json
no matches (0 / 0 / 0)
```

`resolve-conflicts --dry-run` (il piano completo ha 12 elementi, tutti `ADVISE`, 0 `trash`):

```text
ADVISE ~/.claude/plugins/cache/ai-orchestration/architect-side/0.3.0/skills/orchestration-workflow
       (disable plugin architect-side@ai-orchestration in ~/.claude/settings.json (enabledPlugins) or uninstall it)
ADVISE ~/.claude/skills/framework-skillset-generator (standalone copy differs from plugin agent-tooling-meta@agentic-coding-kit ...)
ADVISE ~/.claude/skills/frontend-design | gcube-component-release | gcube-jenkins | gcube-liferay62-release-deploy |
       gcube-repo-standards | gcube-security-audit | kilo-mcp-conflict-resolver | kilo-mcp-orchestrator |
       liferay62-angular-portlet | task-pipeline   (same "differs ... review and remove one manually")
```

### 1. `duplicate-name`: standalone vs plugin (11). VERO, bloccato in un ciclo no-op

Sono reali: Claude Code espone entrambe le copie. Nell'elenco delle skill di questa stessa sessione compaiono sia `gcube-jenkins` sia `gcube-developer-tools:gcube-jenkins`, così come `task-pipeline` e `architect-side:task-pipeline`, e così via.

Confronto del contenuto rispetto al percorso di installazione del plugin **attivo** (da `installed_plugins.json`), escludendo `index.json`, `.DS_Store`, `__pycache__` e `.pytest_cache`:

| Skill | Righe di diff vs plugin attivo | Identica byte per byte a una versione in cache del plugin | Uguale dopo normalizzazione del frontmatter a | Natura della differenza |
|---|---|---|---|---|
| framework-skillset-generator | 134 (vs 0.2.0) | **0.1.0** | 0.1.0 | Versione precedente del plugin. Sicura da eliminare |
| gcube-component-release | 6 | nessuna | **0.2.0, 0.2.1** | Solo ri-serializzazione del frontmatter |
| gcube-liferay62-release-deploy | 8 | nessuna | **0.2.0, 0.2.1** | Solo frontmatter |
| gcube-repo-standards | 6 | nessuna | **0.2.1** | Solo frontmatter |
| liferay62-angular-portlet | 6 | nessuna | **0.2.0, 0.2.1** | Solo frontmatter |
| gcube-jenkins | 6 + dir extra `references/` | nessuna | nessuna | La standalone ha file extra. Divergenza reale |
| gcube-security-audit | 267 + extra `assets/`, `references/`, 3 script | nessuna | nessuna | Divergenza reale (la standalone è più ricca) |
| frontend-design | 93; il plugin ha `LICENSE`, `local.patch` | nessuna | nessuna | Divergenza reale (il plugin ha una patch) |
| task-pipeline | 241 | nessuna | nessuna | Nostra. La standalone è **più recente** del plugin (vedi #10) |
| kilo-mcp-orchestrator | 88 | nessuna | nessuna | Nostra. La standalone è più recente del plugin |
| kilo-mcp-conflict-resolver | 16 | nessuna | nessuna | Nostra. La standalone è più recente del plugin |

Il diff di "solo frontmatter" appare così (standalone vs plugin):

```text
$ diff ~/.claude/skills/gcube-jenkins/SKILL.md ~/.claude/plugins/cache/gcube-ai-toolkit/gcube-developer-tools/0.2.1/skills/gcube-jenkins/SKILL.md
4,6c4,6
< metadata: ""
< author: Alfredo Oliviero
< version: 1.0.0
---
> metadata:
>   author: Alfredo Oliviero
>   version: 1.0.0
```

Le copie standalone sono state scritte da un installer che serializza il frontmatter una riga per chiave e appiattisce la mappa annidata `metadata`. Il pattern è coerente con `ai-swissknife/src/adapters/claude.ts:159-171` (`serializeSkillMarkdown`: ``fm += `${key}: ${serializeYamlValue(value)}\n` ``), but the writer was **not proven**. Either way this is a real, if small, corruption of the copy: `metadata` ha perso i suoi elementi figli.

Perché la segnalazione persiste:

- `orchestration_env.py:1978-1982`: una copia standalone viene cestinata solo se `state == up-to-date`, o se è identica byte per byte a una copia attuale del plugin, o se il suo hash è nel catalogo. Queste skill sono `unmanaged` o `foreign`, e nessuna è identica byte per byte alla versione **attiva** del plugin. Non viene tentato il confronto con versioni precedenti in cache né con il contenuto normalizzato.
- `:2002-2019`: altrimenti diventa `advise` e non viene aggiunto nulla a `c_items`.
- `:2081-2097`: l'applicazione itera solo su `conflict_items`, quindi non sposta nulla, restituisce `ok: true, resolved_count: 0` e la UI chiama `onRefresh()` (`EnvironmentDoctor.tsx:56-58`). Ricompaiono gli stessi banner.
- UI: `hasResolvableConflicts` è vero ogni volta che una voce qualsiasi è standalone (`EnvironmentDoctor.tsx:30-41`). Ciascuno di questi banner è rosso con "Resolve…" (`:317-358`). `ConfirmDialog` supporta `isApplyDisabled` (`ConfirmDialog.tsx:35,452`), ma il Doctor non lo passa mai (`EnvironmentDoctor.tsx:572-585`), quindi "Confirm & Apply" resta abilitato anche su un piano composto interamente da `advise`.

### 2. `trigger-conflict` (Claude). VERO, non risolvibile dal Doctor

Voci: `plugin:architect-side@ai-orchestration` `orchestration-workflow`, standalone `~/.claude/skills/kilo-mcp-orchestrator` (`foreign`) e `plugin:architect-side@kilo-mcp` `kilo-mcp-orchestrator`. Entrambe le descrizioni iniziano con "Orchestrate an Executor agent / Orchestrate Kilo (the Executor) ..." e si sovrappongono quasi parola per parola, quindi la competizione sul trigger è reale.

`load_conflict_policy` imposta di default `claude = bound` (`:536-540`), perciò la skill generica deve essere rimossa. Esistendo solo come plugin, il piano è `ADVISE disable plugin architect-side@ai-orchestration` (`:1926-1943`). Quel plugin fornisce anche `task-pipeline`, `task-spec-authoring`, `task-worktree-ops`, `orchestration-metrics` e `conflict-resolver`, quindi seguire il consiglio rimuoverebbe 5 skill utilizzate dall'owner. Il consiglio è sproporzionato e in pratica l'owner mantiene intenzionalmente entrambi i plugin abilitati (`~/.claude/settings.json` `enabledPlugins`: tutti e 7 a true).

Poiché `kilo-mcp-orchestrator` standalone è in `entries`, `isAllPlugin` è falso (`EnvironmentDoctor.tsx:284`) e il banner è rosso con "Resolve…". Non si risolve mai.

Due osservazioni collaterali:

- La coppia di trigger è cablata nel codice (`:1213-1215`). La coppia analoga `executor-contract` / `kilo-mcp-executor-contract`, presente in tutti e tre gli assistenti, non viene controllata.
- Per Codex e Kilo la coppia cablata causa un effetto ping-pong con `install-skills` (#12).

### 3. `foreign` (17). Per lo più installazioni legacy classificate erroneamente

Metodo: `git hash-object` del file `SKILL.md` installato (o di uno script), seguito da `git log --all --find-object=<blob>` sul file sorgente nel repository del catalogo. Solo il file campionato è stato confrontato tramite blob, non ogni singolo file della directory.

```text
~/.{kilo,claude,codex}/skills/task-pipeline/SKILL.md          -> ai-orchestration 2e5a6c2 2026-10-16
~/.{kilo,claude,codex}/skills/executor-contract/SKILL.md      -> ai-orchestration 927244a 2026-10-15
~/.{kilo,claude,codex}/skills/orchestration-setup/scripts/orchestration_config.py -> ai-orchestration 927244a 2026-10-15
~/.kilo/skills/orchestration-workflow/SKILL.md                -> ai-orchestration 55682fc 2026-10-15
~/.{claude,codex}/skills/kilo-mcp-executor-contract/SKILL.md  -> kilo-mcp ce7e380 2026-10-15
~/.{claude,codex}/skills/kilo-mcp-orchestrator/SKILL.md       -> kilo-mcp 7b674b8 2026-10-15
~/.claude/skills/kilo-mcp-conflict-resolver/SKILL.md          -> no match; diff vs source = 2 lines (description quoted vs unquoted)
~/.claude/skills/kilo-mcp-metrics-analyst/SKILL.md            -> no match; diff vs source = 2 lines (same quoting)
~/.kilo/skills/kilo-mcp-executor-contract/SKILL.md            -> no match; 27 diff lines (quoting + missing "Blocking questions" section = outdated)
```

Quindi 14 su 17 sono **copie obsolete del nostro stesso catalogo**, 2 su 17 sono **semanticamente identiche** (differisce solo la quotatura YAML) e 1 su 17 è obsoleta con frontmatter ri-serializzato. Nessuna è estranea nel senso comune di "proveniente da un'altra fonte".

Il codice è conforme alla regola A4 della specifica (`:436-454`, "nessuna ricevuta e nessuna corrispondenza hash → foreign"). È la regola stessa a etichettare erroneamente le installazioni precedenti all'introduzione delle ricevute. La specifica E4 documenta che il vecchio installer sovrascriveva proprio queste directory, quindi sono nostre.

Perché persistono:

- `install-skills --dry-run` mostra `SKIP ... (Skip foreign skill '<name>': not in --overwrite list)` per 13 di esse (`:1602-1610`).
- L'installer della UI non invia mai `overwrite` (`SkillInstaller.tsx:39`, `:48`, solo `api.ts:287-319` ha il parametro).
- L'unico percorso nella UI è il cestino sulla singola riga (`EnvironmentDoctor.tsx:476-492`) seguito da una reinstallazione, cosa che nessuno scopre. Il badge è ambra senza alcuna spiegazione.

### 4. `unmanaged` (38). FALSO come avviso

`discover_available_skills` scansiona solo `ai-orchestration`, `kilo-mcp`, `claude-mcp` (`:339`). Tutto il resto è `unmanaged`: le skill del toolkit gcube, le skill di terze parti, `impeccable`, le skill `d4science-*`, `ai-debugger` di progetto e così via. Sono legittime e non rappresentano un disallineamento. Il colore del badge di stato ricade sull'ambra (`#451a03`/`#fbbf24`) per qualsiasi stato diverso da `up-to-date`, `plugin` o `obsolete*` (`EnvironmentDoctor.tsx:455-470`), lo stesso colore di `foreign`. Così 38 voci sembrano problemi.

### 5. Lo scope di progetto di Claude duplica la vista globale. FALSO (presentazione)

`inspect_environment` aggiunge tutte le skill dei plugin con scope `user` alle voci di progetto (`:1138-1149`) e calcola i conflitti di progetto sulle voci di progetto + le standalone globali (`:1192-1195`). La sezione di progetto ripete quindi gli stessi 12 conflitti e le 33 righe dei plugin (34 nella vista AO). L'owner vede 24 banner rossi per 12 problemi.

### 6. Duplicati standalone di progetto vs globali (workspace AO, 5). VERO, nessun percorso di risoluzione

```text
duplicate-name executor-contract          [project up-to-date, global foreign]
duplicate-name kilo-mcp-executor-contract [project up-to-date, global foreign]
duplicate-name kilo-mcp-metrics-analyst   [project up-to-date, global foreign]
duplicate-name kilo-mcp-rag-explorer      [project up-to-date, global up-to-date]
duplicate-name orchestration-setup        [project up-to-date, global foreign]
```

- Le copie di progetto hanno ricevute con `installed_at: 2026-10-17T11:13:24Z`, quindi provengono da un'esecuzione di `install-skills --scope project` avvenuta oggi.
- `git status` mostra `?? .claude/`, `?? .codex/`, `?? .kilo/skills/`, `?? .kilo/agents/`, `?? .kilo/kilo.json`: non tracciati e non ignorati.
- `resolve_conflicts` gestisce `duplicate-name` solo quando `standalone_entries and plugin_entries` (`:1949`) o solo plugin (`:2021`). I duplicati solo standalone non ricevono alcun elemento nel piano, mentre la UI li mostra in rosso con "Resolve…".
- Serve una decisione dell'owner (non del Doctor): mantenere queste copie di progetto (aggiungendole a `.gitignore` o committandole) oppure rimuoverle.

### 7. File orfano `~/.codex/config.json`. VERO, non risolvibile automaticamente

- Data di modifica `Oct 15 14:21:38 2026`, identica a `~/.config/kilo/kilo.json`. Questo corrisponde alla specifica E3: lo ha scritto il vecchio `register-mcp`.
- Contenuto: `mcpServers: {kilo-mcp (.venv/bin/python server.py), codex-mcp}`.
- Codex legge `config.toml`, che contiene `kilo-mcp` (tramite `uv run`), `playwright`, `vscode-dap`. Quindi la voce `codex-mcp` del JSON non è mai stata attiva per Codex.
- Il rilevamento (`:1298-1301`) è corretto. La specifica §2.1 dice di "segnalarli ... senza eliminarli", quindi non c'è alcuna azione e il banner resta per sempre. Il testo del banner ("ignored by the assistant's runtime", `EnvironmentDoctor.tsx:165-187`) è accurato ma non indica il passo successivo.
- Separatamente, anche `ai-swissknife/src/adapters/codex.ts:243` punta a `~/.codex/config.json`. È un secondo componente da correggere in quel repository, altrimenti il file tornerà a comparire.

### 8. Override MCP di Kilo (`playwright`). VERO ma innocuo

`~/.config/kilo/kilo.json` e `kilo.jsonc` definiscono entrambi `playwright` come `["npx","-y","@playwright/mcp@0.0.38"]`, quindi le definizioni sono identiche. Il lettore di merge aggiunge una voce a `overrides` a qualsiasi ridefinizione (`:793-799`) senza confrontare il contenuto, e la UI la mostra in ambra (`EnvironmentDoctor.tsx:540-544`). La precedenza di merge propria di Kilo fa vincere `kilo.jsonc` (spec A1), quindi non c'è nulla di rotto.

### 9. Agente `kilo-mcp-orchestrator-agent.md` (Claude, `foreign`). FALSO, non renderizzato

```text
$ diff ~/.claude/agents/kilo-mcp-orchestrator-agent.md kilo-mcp/plugins/architect-side/agents/kilo-mcp-orchestrator-agent.md
3a4,9
> mode: subagent
> permission: {read, edit, bash, mcp: allow}
```

- La copia di Claude è l'agente di Kilo privato del frontmatter specifico di Kilo, un adattamento deliberato.
- `install_skills` copia lo stesso file agente identico su Claude e Kilo (`:1523-1580`), quindi una reinstallazione inserirebbe i campi di Kilo in Claude.
- `EnvironmentDoctor.tsx` non renderizza mai `agents` (0 occorrenze), perciò l'owner non lo vede mai.

### 10. Copie dei plugin di Claude obsolete. Controllo mancante

```text
installed_plugins.json: architect-side@ai-orchestration 0.3.0 gitCommitSha 30521e8a (2026-10-15 12:33) -> 69 commits behind ai-orchestration HEAD
                        architect-side@kilo-mcp        0.2.2 gitCommitSha 1a35cc0                    -> 7 commits behind kilo-mcp HEAD
plugin.json versions in the repos today: 0.3.0 and 0.2.2 (unchanged, so Claude has no reason to update)

diff lines vs source repo (excl. index.json, fixtures, caches):
  task-pipeline           standalone 7546 | plugin 7681
  kilo-mcp-orchestrator   standalone   19 | plugin  107
  kilo-mcp-conflict-res.  standalone    2 | plugin   14
```

In tutte e tre le sovrapposizioni con le nostre skill, la copia standalone è più vicina al sorgente rispetto alla copia del plugin. La regola di risoluzione "plugin copy kept" (`:1988`) manterrebbe quindi la copia più vecchia. Le voci dei plugin hanno sempre stato `plugin` (`:1136`) senza alcun controllo di disallineamento.

### 11. Insieme effettivo delle skill di Kilo. Controllo mancante

Sorgente di Kilo (`references/kilocode/kilocode/packages/opencode/src`):

- `skill/index.ts:24-25,29-30`: directory esterne `.claude`, `.agents` con pattern `skills/**/SKILL.md`; directory di configurazione con `{skill,skills}/**/SKILL.md`.
- `skill/index.ts:240-246`: scansione globale di `~/.claude/skills` e `~/.agents/skills` a meno che non sia impostato `KILO_DISABLE_CLAUDE_CODE_SKILLS` / `KILO_DISABLE_EXTERNAL_SKILLS`. Nessuno dei due è impostato e la configurazione non lo disabilita.
- `skill/index.ts:271-282` + `config/paths.ts:23-40`: directory di configurazione = `~/.config/kilo` + `.kilo`/`.kilocode` trovate risalendo dalla home e dal progetto.

Il Doctor scansiona solo `~/.kilo/skills` (`assistant_skills_dir`, `:259-274`). Skill con lo stesso nome che Kilo vede da più di una radice, escludendo le skill sincronizzate dall'account Claude:

```text
executor-contract, framework-skillset-generator, frontend-design, gcube-jenkins, gcube-liferay62-release-deploy,
gcube-repo-standards, gcube-security-audit, kilo-mcp-conflict-resolver, kilo-mcp-executor-contract,
kilo-mcp-metrics-analyst, kilo-mcp-rag-explorer, orchestration-setup, task-pipeline   (~/.kilo/skills + ~/.claude/skills)
toolkit-release-manager                                   (~/.config/kilo/skills + ~/.kilo/skills + ~/.claude/skills)
```

Sono 14. Inoltre:

- Kilo vede `orchestration-workflow` (`~/.kilo/skills`) **e** `kilo-mcp-orchestrator` (`~/.claude/skills`): un vero conflitto di trigger in Kilo che il Doctor riporta come "no conflicts".
- `~/.claude/skills/synced/**` (skill sincronizzate dall'account Claude, fino a 4 copie ciascuna di `docx`, `pdf`, `pptx`, …) e `~/.claude/skills/.trash/**` (5 `SKILL.md`) rientrano nel glob `skills/**` di Kilo con `dot: true`. Probabilmente anche queste vengono caricate da Kilo; non verificato a runtime.

### 12. `install-skills` crea i conflitti che `resolve-conflicts` poi segnala

Da `install-skills --dry-run --assistants all --scope global`:

```text
CREATE ~/.claude/skills/{conflict-resolver, orchestration-metrics, orchestration-workflow, task-spec-authoring, task-worktree-ops}
CREATE ~/.codex/skills/orchestration-workflow
```

- Tutti e 5 i nomi di Claude sono già forniti dal plugin abilitato `architect-side@ai-orchestration`, quindi applicare il piano aggiungerebbe 5 nuovi conflitti `duplicate-name`.
- `orchestration-workflow` in Claude/Codex è esattamente ciò che la policy `bound` rimuove. Installazione e risoluzione si annullano a vicenda.
- Il piano di installazione (`:1583-1619`) non considera né i plugin né la policy dei conflitti.

### 13. Piano di `register-mcp`

```text
EDIT ~/.config/kilo/kilo.json   current_state unregistered   (adds kilo-mcp to Kilo itself)
CLI  claude mcp add --scope user kilo-mcp -- .../kilo-mcp/.venv/bin/python .../server.py   current_state: registered
CLI  codex mcp add kilo-mcp -- .../kilo-mcp/.venv/bin/python .../server.py                current_state: registered
```

- Entrambi gli elementi CLI vengono eseguiti anche se il server è già registrato. La registrazione esistente usa `uv run --no-project --with mcp>=2 python .../server.py`, quindi l'elemento sostituirebbe il comando di avvio scelto dall'owner, oppure fallirebbe. Il comportamento di `claude mcp add` con un nome già esistente non è stato verificato.
- Registrare `kilo-mcp` dentro Kilo significa che Kilo delega a Kilo, il che è discutibile come impostazione predefinita per `--assistants all`.
- Questa non è una segnalazione del Doctor, ma fa parte del problema "le correzioni non funzionano come previsto".

## Modifiche proposte (in ordine di priorità, ciascuna pronta a diventare un task)

### P1-a. Interrompere il ciclo no-op di "Resolve" (S)

- **Obiettivo:** un conflitto viene mostrato come risolvibile solo quando il piano contiene un'azione eseguibile per esso. Un piano composto solo da avvisi non può essere "applicato".
- **File:**
  - `scripts/orchestration_env.py`: in `inspect_environment`, allegare a ciascun elemento di `structured_conflicts` i campi `actionable: bool` e `advice: str`, calcolati con le stesse regole usate da `resolve_conflicts`. Fattorizzare la decisione per singolo conflitto in un'unica funzione condivisa da entrambi.
  - `EnvironmentDoctor.tsx`: rosso + "Resolve…" solo se `actionable`. `hasResolvableConflicts` usa `actionable`. Passare `isApplyDisabled` quando il piano non ha elementi `trash`/`replace` e cambiare l'etichetta del pulsante in "Nothing to apply".
- **Verifica:** sulla home attuale, il Doctor non mostra alcun "Resolve…" rosso per i 12 conflitti di Claude (diventano info/avvisi). Una fixture di test con una coppia standalone+plugin identica byte per byte mostra ancora il rosso e risolve il conflitto. Unit test: un piano con soli `advise` imposta `isApplyDisabled`.

### P1-b. Modello di severità, deduplicazione, presa d'atto (M)

- **Obiettivo:** l'owner vede solo ciò che richiede un'azione. Tutto ciò che è noto e accettato rimane silenzioso finché non cambia.
- **Livelli di severità:**
  - `error`: conflitto risolvibile.
  - `warning`: disallineamento risolvibile (`outdated-legacy`, `modified-or-outdated`, `plugin-stale`, override MCP in conflitto).
  - `info`: vero ma non risolvibile automaticamente (conflitti tra soli plugin, conflitto di trigger con plugin, file orfano, override MCP ridondante).
  - `neutral`: `unmanaged`/esterno, `plugin`.
- **Raggruppamento:** raggruppare per tipo tra gli assistenti ("11 skills duplicated between ~/.claude/skills and Claude plugins"), espandibile per singolo elemento. Nello scope di progetto mostrare solo i conflitti che coinvolgono una voce di progetto, più una riga "N conflicts inherited from global".
- **Presa d'atto (Acknowledge):** per singola segnalazione, salvata in modo persistente in `~/.config/ai-orchestration/doctor-ack.json`, scritta solo tramite un comando CLI con anteprima (`env ack --dry-run/--expect-plan-hash`). La chiave è `(assistant, scope, kind, names, sorted content hashes of the entries)`, così una segnalazione riconosciuta ricompare quando una copia qualsiasi cambia. Un interruttore "show acknowledged".
- **Testo di spiegazione per tipo:** cosa significa, perché il Doctor non può risolverlo, il passo manuale esatto. Esempi:
  - "Claude loads both copies; the plugin is managed by Claude's plugin manager. To remove the standalone copy use the trash icon; to remove the plugin copy disable `<id>` in enabledPlugins."
  - Per il conflitto di trigger: "disabling `architect-side@ai-orchestration` also removes task-pipeline, task-spec-authoring, …".
- **File:** `orchestration_env.py` (campo severità, archivio ack + comando `env ack`), `EnvironmentDoctor.tsx`, `server.py` (endpoint ack con anteprima/applicazione), tipi.
- **Verifica:**
  - Sulla home attuale la parte superiore del Doctor mostra ≤ 5 gruppi.
  - Riconoscere il conflitto di trigger lo nasconde, e ricompare dopo aver modificato il `SKILL.md` standalone in una home fittizia.
  - Le righe `unmanaged` sono grigie.

### P1-c. Risoluzione più intelligente dei duplicati: uguaglianza e cronologia (M)

- **Obiettivo:** risolvere automaticamente le copie standalone che sono solo versioni più vecchie o ri-serializzate di ciò che fornisce un plugin o il catalogo.
- **Regole**, in ordine (una voce standalone è sicura da cestinare, mantenendo il plugin, quando vale una qualsiasi delle seguenti condizioni):
  1. identica byte per byte alla copia del plugin attivo (regola odierna);
  2. identica byte per byte a **qualsiasi versione in cache** dello stesso plugin sotto `~/.claude/plugins/cache/<marketplace>/<plugin>/*/skills/<name>`;
  3. uguale dopo la normalizzazione del frontmatter: parsing YAML, unione di un `metadata` appiattito, rimozione dei valori vuoti, confronto del corpo + chiavi analizzate;
  4. per le nostre skill, il blob di ogni file è nella cronologia git del sorgente del catalogo **e** la copia del plugin non è più vecchia (vedi P1-d).

  Altrimenti avvisare, con un link al diff.
- **Risultato atteso su questa macchina:** 5 su 11 diventano risolvibili automaticamente (framework-skillset-generator, gcube-component-release, gcube-liferay62-release-deploy, gcube-repo-standards, liferay62-angular-portlet). gcube-jenkins, gcube-security-audit e frontend-design restano come avviso con diff. task-pipeline, kilo-mcp-orchestrator e kilo-mcp-conflict-resolver attendono P1-d.
- **File:** `orchestration_env.py` (`resolve_conflicts` `:1945-2044`, nuovo helper `skill_equivalent(a, b)`), test.
- **Verifica:** una home fittizia che riproduce l'appiattimento del frontmatter di gcube-jenkins si risolve in `trash`. Una fixture con un file extra resta `advise`. `resolve-conflicts --dry-run` sulla home reale elenca esattamente quei 5 elementi `trash`.

### P1-d. Rilevare le copie obsolete dei plugin (S/M)

- **Obiettivo:** segnalare quando un plugin di Claude proveniente da un marketplace del catalogo (`ai-orchestration`, `kilo-mcp`) è indietro rispetto al repository sorgente, e non applicare mai "keep plugin copy" quando il plugin è la copia più vecchia.
- **Come:**
  - confrontare in `installed_plugins.json` il campo `gitCommitSha` con `HEAD` del repository sorgente, più un hash del contenuto per ogni skill rispetto al catalogo;
  - nuovo stato della voce `plugin-stale`, severità warning;
  - avviso "bump `plugin.json` version and run `/plugin update <id>`", o il flusso di aggiornamento del marketplace.
- **File:** `orchestration_env.py` (`discover_claude_plugin_skills`, `inspect_environment`, regola di mantenimento in `resolve_conflicts`), badge nella UI.
- **Verifica:** sulla home attuale entrambi i plugin architect-side mostrano `plugin-stale` (69 e 7 commit indietro). Una fixture in cui il plugin è aggiornato mostra `plugin`.

### P2-a. Classificazione consapevole della cronologia per le installazioni legacy (M)

- **Obiettivo:** le copie delle nostre skill installate prima che esistessero le ricevute vengono mostrate come `outdated-legacy` (o `up-to-date` quando differisce solo la quotatura del frontmatter), non `foreign`. L'owner può aggiornarle dalla UI.
- **Come:**
  - in `detect_skill_state` (`:436-454`), prima di restituire `foreign`, verificare se il blob di ogni file compare in `git log --all --find-object` del percorso corrispondente nel catalogo (con cache per singola esecuzione), o se il contenuto è uguale al catalogo a meno del frontmatter;
  - aggiornare la regola A4 della specifica per aggiungere lo stato;
  - la UI riceve un'azione di riga "Update…" che invoca `install-skills --overwrite <name>` con anteprima.
- **File:** `orchestration_env.py`, `tasks/specs/control-plane-safety.md` (emendamento A4), `SkillInstaller.tsx`/`EnvironmentDoctor.tsx`, `server.py` (passaggio di `overwrite`).
- **Verifica:** sulla home attuale, 0 `foreign` tra le 17 (14 `outdated-legacy`, 2 `up-to-date`, 1 `outdated-legacy`). Il dry-run di "Update" su `~/.codex/skills/task-pipeline` mostra `replace` con gli hash prima/dopo.

### P2-b. Vista effettiva di Kilo (M)

- **Obiettivo:** la sezione di Kilo riflette ciò che Kilo carica: `~/.kilo/{skill,skills}`, `~/.config/kilo/{skill,skills}`, `~/.claude/skills/**` (a meno di `KILO_DISABLE_CLAUDE_CODE_SKILLS`), `~/.agents/skills/**`, `.kilo`/`.kilocode`/`.claude`/`.agents` di progetto e `skills.paths` dalla configurazione Kilo unificata.
- **Come:** le voci riportano `origin: standalone:<root>` e i conflitti vengono calcolati su tale unione. `install`/`remove` continuano a puntare solo a `~/.kilo/skills`.
- **File:** `orchestration_env.py` (`inspect_environment`, nuova `kilo_skill_roots()`), colonna origin nella UI.
- **Verifica:** sulla home attuale Kilo mostra i 14 duplicati tra radici diverse elencati nell'evidenza #11 e il conflitto di trigger. Impostando `KILO_DISABLE_CLAUDE_CODE_SKILLS=1` nell'ambiente della CLI vengono rimossi quelli di `~/.claude`.

### P2-c. Fare in modo che l'installazione rispetti i plugin e la policy (S)

- **Obiettivo:** `install-skills` non crea più i conflitti che `resolve-conflicts` segnala.
- **Regole:**
  - destinazione Claude: saltare con motivo "provided by enabled plugin `<id>`" quando un plugin abilitato fornisce quel nome;
  - saltare i nomi che `[env.conflicts] keep` rimuoverebbe in quell'assistente (ad es. `orchestration-workflow` per Claude/Codex sotto `bound`);
  - `--force` ignora entrambe le regole.
- **File:** `orchestration_env.py` (`install_skills` `:1583-1619`), test.
- **Verifica:** `install-skills --dry-run --assistants all --scope global` sulla home attuale mostra i 5 elementi `CREATE` di Claude e l'elemento `orchestration-workflow` di Codex come `SKIP` con tali motivazioni.

### P2-d. Duplicati solo standalone (S)

- **Obiettivo:** i duplicati standalone di progetto rispetto a quelli globali ricevono un piano. Contenuto identico → cestinare la copia di progetto (default; la regola può essere configurata come `keep_scope = project|global`). Contenuto diverso → avvisare con diff.
- **File:** `orchestration_env.py` (`resolve_conflicts`).
- **Verifica:** il dry-run sul workspace AO elenca `kilo-mcp-rag-explorer` (entrambe aggiornate) come `trash` di una copia, e le altre 4 secondo la regola scelta. Nessun banner rosso privo di elemento nel piano.

### P3-a. Azioni per file orfani e override MCP ridondanti (S)

- **Obiettivo:** il banner del file orfano e gli override MCP ridondanti possono essere eliminati.
- **Come:**
  - `env clean-stray --dry-run/--expect-plan-hash` sposta `~/.codex/config.json` nel cestino di ai-orch. L'anteprima elenca ciascun server contenuto al suo interno e indica se `config.toml` lo possiede già.
  - `read_kilo_merged_mcps` contrassegna un override con `identical: true|false`. Un override identico è di livello info, con una modifica in anteprima che rimuove la voce da `kilo.json`.
  - Aprire un follow-up in `ai-swissknife` per smettere di scrivere `~/.codex/config.json` (`src/adapters/codex.ts:243`).
- **Verifica:** in una home fittizia con entrambi i file, il piano dry-run elenca un `trash` e un `edit`. Dopo l'applicazione, `env status` non mostra alcun file orfano né alcun override.

### P3-b. Idempotenza di `register-mcp` (S)

- **Obiettivo:** nessuna chiamata CLI quando il server è già registrato con un comando equivalente. Altrimenti un elemento `replace` che mostri il vecchio e il nuovo comando. `--assistants all` non registra `kilo-mcp` dentro Kilo a meno che non venga richiesto esplicitamente.
- **File:** `orchestration_env.py` (`register_mcp_server` `:2124-2427`).
- **Verifica:** sulla home attuale il dry-run mostra `noop` per Claude e Codex (oppure `replace` mostrando `uv run …` → `.venv/bin/python …`), e nulla per Kilo di default.

### P3-c. Agenti nel Doctor (M)

- **Obiettivo:**
  - renderizzare gli agenti (stato, origine);
  - installare gli agenti tramite una trasformazione per assistente: omettere `mode`/`permission` specifici di Kilo per Claude;
  - le ricevute calcolano l'hash dell'output trasformato, così un agente adattato correttamente risulta `up-to-date`.
- **File:** `orchestration_env.py` (ramo agenti di `install_skills`, `detect_agent_state`), `EnvironmentDoctor.tsx`.
- **Verifica:** `~/.claude/agents/kilo-mcp-orchestrator-agent.md` viene classificato come `up-to-date` (o `outdated-legacy`) invece di `foreign`.

### P3-d. Generalizzazione dei conflitti di trigger (S)

- **Obiettivo:** le coppie generica/associata provengono dai binding (`kilo-mcp/bindings/*.json`), non da una coppia cablata nel codice. Ciò copre `executor-contract`/`kilo-mcp-executor-contract`, `conflict-resolver`/`kilo-mcp-conflict-resolver` e `orchestration-metrics`/`kilo-mcp-metrics-analyst`. L'avviso elenca ogni skill che scomparirebbe disabilitando un plugin.
- **File:** `orchestration_env.py` (`:1213-1236`, `resolve_conflicts`).
- **Verifica:** la fixture con una skill generica presente solo come plugin mostra un avviso che elenca le altre skill del plugin.

## Decisioni dell'owner emerse (non lavoro sul Doctor)

1. Mantenere abilitati sia `architect-side@ai-orchestration` sia `architect-side@kilo-mcp` in Claude (e quindi riconoscere il conflitto di trigger), oppure cambiare la policy di Claude in `generic`.
2. Incrementare le versioni dei plugin (`ai-orchestration` architect-side 0.3.0, `kilo-mcp` architect-side 0.2.2) e aggiornare i plugin di Claude. Oggi Claude esegue copie dei plugin vecchie di 69 e 7 commit.
3. I file non tracciati `ai-orchestration/.claude/skills`, `.codex/skills`, `.kilo/skills`, `.kilo/agents`, `.kilo/kilo.json` scritti oggi alle 11:13Z: mantenerli (in gitignore o committati) oppure rimuoverli.
4. Le copie standalone di `gcube-jenkins`, `gcube-security-audit` e `frontend-design` contengono contenuti extra reali rispetto al plugin. Decidere quale copia è canonica e portare i contenuti extra in `gcube-ai-toolkit` / `agentic-coding-kit` se si desidera conservarli.

## Controllo di integrità della home

All'inizio è stato creato un marker (`tasks/env-doctor/notes/.marker`). L'output di `find` al termine è registrato nel messaggio di consegna della sessione, non in questo file.
