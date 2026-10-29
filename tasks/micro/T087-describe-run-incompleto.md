# T087 ai-orch describe elenca solo una parte dei sottocomandi di run

- id: T087
- title: ai-orch describe elenca solo una parte dei sottocomandi di run
- kind: fix
- priority: P3
- state: in progress
- executor: kilo
- paths: bin/ai-orch
- depends-on: -
- short: describe run incompleto

## What

`ai-orch describe` (`bin/ai-orch:520-545`) elenca per `run` solo `options`, `preview`, `list`, `show`. Mancano `start`, `cancel`, `logs`, `mark-delivered`, `apply-verdict`, `accept-triage`, `cleanup`, `kilo-agent`. Generare l'elenco dal parser invece di mantenerlo a mano, con un test che confronta describe e parser. Fonte: N081 punto 8, revisione 2026-10-29 della spec multi-macchina.

## Log (newest first)

- 2026-10-29, orchestrator: state `open` -> `in progress` — kilo (gemini-3.8-flash) in screen su alf_ubuntu
