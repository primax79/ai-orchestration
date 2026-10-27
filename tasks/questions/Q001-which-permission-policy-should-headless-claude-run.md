# Q001 Quale policy di permessi devono usare di default le run headless di Claude, per modalità

- id: Q001
- question: Quale policy di permessi devono usare di default le run headless di Claude, per modalità?
- status: answered
- blocks: -
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-17
- origin-run: -
- open-answer: yes
- recommended: A
- applied: yes
- short: Permessi Claude headless

## Context

Le run headless di Claude (`claude -p`) non possono mostrare prompt di conferma dei permessi. Il motore di esecuzione (iniziativa 07) le avvia con `--permission-mode acceptEdits --permission-prompts none`: le modifiche ai file sono consentite, ma ogni tool che normalmente chiederebbe conferma viene negato, inclusi Bash fuori da una allow-list e i tool MCP. Senza una allow-list, una run `execute` non può eseguire i test o `git commit`, e una run `orchestrate` non può invocare kilo-mcp.

Oggi 07.3 rifiuta di avviare Claude quando non è configurato alcun `allowed_tools` per la modalità, quindi di default non accade nulla di insicuro; tuttavia le run restano inutilizzabili finché non viene presa questa decisione.

Dove si applica: le run `execute` lavorano in un worktree git isolato (le scritture sono confinate a quel worktree, ma Bash può comunque raggiungere il resto della macchina); le run `verify` lavorano in un worktree detached temporaneo; le run `orchestrate` lavorano nel workspace principale e richiedono i tool MCP (kilo-mcp) e git.

L'impostazione risiede in `orchestration.toml` sotto `[tools.claude.headless]` (per modalità), e la finestra di dialogo Run la mostra; una modalità pericolosa viene evidenziata in rosso.

## Options

- **A** — Allow-list per modalità: execute e verify ricevono Bash(git:*), i test runner (pytest, npm test, uv run) e i tool per i file; orchestrate riceve anche i tool kilo-mcp. Sicura, ma una run si blocca su qualsiasi comando non elencato (visibile nel relativo log).
- **B** — Allow-list ampia: Bash(*) più tutti i tool MCP, sempre con acceptEdits. Le run non si bloccano mai sui permessi, ma qualsiasi comando shell è consentito su questa macchina.
- **C** — bypassPermissions per execute/verify (solo dentro i worktree), allow-list A per orchestrate: la più semplice per gli esecutori, accesso completo alla macchina per quelle run.

## Answer

- choice: A
- answered-by: owner
- answered: 2026-10-17
