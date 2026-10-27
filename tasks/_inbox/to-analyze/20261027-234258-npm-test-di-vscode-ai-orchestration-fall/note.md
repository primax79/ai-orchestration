# N076 npm test di vscode-ai-orchestration fallito una volta, non riprodotto

- id: N076
- title: npm test di vscode-ai-orchestration fallito una volta, non riprodotto
- kind: bug
- status: ready
- created: 2026-10-27T23:42:58.977040+00:00
- author: ai-coding-tools-87
- about: -
- produced: -
- processed-by: -
- short: Test intermittente estensione

2026-10-28 00:37, subito dopo il merge di T075 (0.6.6) su main di vscode-ai-orchestration: npm test fallito una volta con AssertionError (operator: 'strictEqual', Node 20.20.2). Output del primo fallimento non conservato (pipeline con tail). Esecuzioni successive: 2 complete + 15 script singoli + ciclo di 8: tutte verdi. Contesto: in parallelo giravano run Kilo (49.6, T071) e la suite pytest; ipotesi test sensibile ai tempi o al carico (test-event-watcher, test-refresh-loop, test-validate-close che usa ai-orch reale). Se ricapita: conservare l'output completo, individuare lo script e la causa.
