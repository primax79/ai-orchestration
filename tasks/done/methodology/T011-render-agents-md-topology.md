# T011 render-agents-md: generare regole coerenti con la reale topologia orchestratore/esecutore

- id: T011
- title: render-agents-md: generare regole coerenti con la reale topologia orchestratore/esecutore
- category: methodology
- priority: P1
- priority-reason: Un blocco applicato guida ogni sessione futura; un blocco errato (orchestratore sbagliato, tool estranei, regole sui modelli contraddittorie) fuorvia silenziosamente gli agenti
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: ../../status/agents-md-generated-block-2026-10-16.md in the ai-coding-tools workspace (block found applied without explanation on 2026-10-16, reviewed and removed)
- paths: plugins/shared/skills/orchestration-setup/scripts/orchestration_config.py
- handoff: Leggere tasks/methodology/T011-render-agents-md-topology.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e tasks/00-INDEX.md.
- verifier: claude:orchestration
- use-cases: UC009
- short: Topologia render-agents-md

## Goal

Il blocco che `render-agents-md` scrive nel file `AGENTS.md` di un workspace rispecchia la topologia reale del workspace. Non prescrive mai tool o modelli che la sessione di orchestrazione non può utilizzare.

Un blocco applicato a `ai-coding-tools/AGENTS.md` il 2026-10-16 presentava quattro problemi:

- Dichiarava `primary_orchestrator = "kilo"` preso dai default globali, sebbene il workspace non abbia una configurazione di progetto e sia di fatto orchestrato da Claude che delega a Kilo tramite MCP.
- La sua Regola 3 prescriveva tool nativi di Kilo (`agent_manager`, `task`).
- La sua Regola 4 elencava modelli di Kilo (`google/gemini-4-argon`) che la regola dell'owner (Kilo sempre su `google/gemini-3.8-flash`) contraddice e che kilo-mcp non offre.
- Introduceva una regola rigida di "nessuna implementazione nella sessione principale" che l'owner non ha mai approvato.

## Steps

1. **Generazione consapevole della topologia.** I tool di isolamento e di delega dipendono dalla coppia (orchestratore, esecutore).
   - Stesso framework: i tool nativi dell'orchestratore.
   - Framework diversi: i tool del binding MCP (ad esempio `kilo_implement(isolation="worktree")` quando Claude orchestra e Kilo esegue; i tool `claude-mcp` nella direzione opposta).
   - I nomi dei tool provengono dalle tabelle dei tool nella configurazione (`native_*_tool`, `mcp_server`, `mcp_implement_tool`), mai da testo cablato specifico per Kilo.
2. **Nessun default silenzioso.** Quando il workspace non ha una configurazione di progetto, `--apply` rifiuta l'operazione e indica il routing che utilizzerebbe; `--allow-global-routing` lo forza. `--diff` mostra lo stesso avviso.
3. **Modelli solo dalla configurazione effettiva.** Prima di generare, validare ogni ID di modello elencato rispetto al catalogo del tool quando quel tool può elencarne uno (ad esempio `kilo models`). Gli ID sconosciuti producono un avviso in `--diff` e un rifiuto con `--apply`, a meno che non venga passato `--allow-unknown-models`.
4. **Le regole prescrittive sono opt-in.** La Regola 1 ("mantenere libera la sessione principale") viene generata nella versione rigida solo quando la configurazione imposta `[agents_md] strict_main_session = true`. Il default usa una formulazione più morbida.

## Verification

- Gli unit test generano il blocco per tre coppie: claude→kilo, kilo→kilo, codex→kilo.
  - La generazione claude→kilo nomina `kilo_implement`, non `agent_manager`.
  - La generazione kilo→kilo nomina `agent_manager`/`task`.
- `--apply` rifiuta l'esecuzione su un workspace privo di configurazione di progetto.
- `--diff` su `/Users/Alfredo/works/ai-coding-tools` (in sola lettura) mostra l'avviso sul routing.
- Non viene applicato nulla ad alcun workspace reale.

## Risultato

Consegnata l'implementazione dei passaggi 1–4 in `orchestration_config.py` con i relativi test:
- **Generazione consapevole della topologia:** I meccanismi di coppia e le skill sono derivati dinamicamente dalle tabelle dei tool della configurazione effettiva (`native_*_tool`, `mcp_server`, `mcp_implement_tool`, `mcp_wait_tool`). Testato per le coppie claude→kilo, kilo→kilo e codex→kilo.
- **Nessun default silenzioso:** I workspace privi di configurazione di progetto fanno sì che `--apply` rifiuti l'operazione e dichiari il routing di fallback a meno che non venga passato `--allow-global-routing`; `--diff` include l'avviso sul routing in `warnings`.
- **Validazione del catalogo modelli:** Gli ID dei modelli elencati per Kilo vengono verificati tramite `kilo models` (con timeout di 20 s e caching in memoria), rifiutando l'esecuzione con `--apply` a meno che non sia specificato `--allow-unknown-models`; la validazione saltata per Claude e Codex viene segnalata negli avvisi.
- **Regole rigide opt-in:** La Regola 1 adotta di default un orientamento architetturale più flessibile e genera il divieto tassativo di implementazione nella sessione principale solo quando `strict_main_session = true` è configurato esplicitamente.
