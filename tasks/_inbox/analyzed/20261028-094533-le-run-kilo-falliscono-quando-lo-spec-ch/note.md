# N077 Le run Kilo falliscono quando lo spec chiede di leggere cartelle fuori dal progetto

- id: N077
- title: Le run Kilo falliscono quando lo spec chiede di leggere cartelle fuori dal progetto
- kind: bug
- status: processed
- created: 2026-10-28T09:45:33.035847+00:00
- author: ai-coding-tools-87
- about: -
- produced: workspace:ai-coding-tools/T040
- processed-by: ai-coding-tools-87

2026-10-28, ai-swissknife 49.7 (due run, c481eee5d60c e e923046cc4f2): lo spec chiedeva un controllo sui dati reali copiando ~/.ai-swissknife, ~/.claude, ~/.kilo in una cartella temporanea. Kilo chiede il permesso external_directory, la run non interattiva lo rifiuta e termina con exit 1 a lavoro quasi finito (nel secondo caso modifiche non committate). Proposte: (a) kilo-mcp avverte in preflight quando lo spec cita percorsi assoluti o ~ fuori dal working_directory; (b) opzione per pre-autorizzare cartelle in sola lettura per una run; (c) la skill per scrivere spec dice di fare i controlli sui dati reali dal lato orchestratore.
