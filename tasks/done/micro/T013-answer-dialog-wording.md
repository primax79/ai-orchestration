# T013 La finestra di conferma della risposta mostra "No modifications required"

- id: T013
- title: La finestra di conferma della risposta mostra "No modifications required"
- category: micro
- priority: P3
- priority-reason: Cosmetico; la risposta viene applicata correttamente
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: architect live check of 08.4 (2026-10-17)
- paths: ../ai-orchestration-ui/frontend/src/components/DecisionsTab.tsx
- handoff: Leggere tasks/micro/T013-answer-dialog-wording.md e correggere il problema.
- verifier: claude:orchestration
- short: Testo dialogo risposta

## Goal

La finestra di dialogo di conferma per rispondere a una domanda mostra il testo riutilizzato dalla vista diff "No modifications required". Dovrebbe invece mostrare l'opzione scelta, il testo libero e l'effetto sui task bloccati (ad esempio "T007 returns to open").

## Steps

1. Passare un corpo di riepilogo invece di un diff vuoto a ConfirmDialog nel flusso di risposta.

## Verification

La finestra di dialogo mostra la scelta e l'effetto; la risposta continua a essere applicata correttamente.
