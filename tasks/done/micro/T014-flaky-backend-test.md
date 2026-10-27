# T014 Un test del backend è fallito una volta su undici esecuzioni

- id: T014
- title: Un test del backend è fallito una volta su undici esecuzioni
- category: micro
- priority: P2
- priority-reason: Un test instabile nasconde le regressioni reali e abitua a rilanciare i test invece di analizzare i fallimenti
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: architect review of 09.2 (2026-10-17): the first run after rebase reported "1 failed, 34 passed"; ten further runs were green and the failing test name was not captured
- paths: ../ai-orchestration-ui/backend/test_server.py
- handoff: Leggere tasks/micro/T014-flaky-backend-test.md e correggere il problema.
- verifier: claude:orchestration
- short: Test backend instabile

## Goal

Individuare e correggere il test dipendente dalle tempistiche in `backend/test_server.py`. I candidati probabili sono il broadcast del watcher entro 2 s, il test di concorrenza della CLI lenta e i test di pulizia del gruppo di processi, eseguiti mentre quattro task di Kilo stavano caricando la macchina.

## Steps

1. Eseguire la suite in ciclo continuo sotto carico CPU (ad esempio 4 `yes > /dev/null` in parallelo), con `-rf -x`, finché non fallisce. Registrare quale test è fallito.
2. Sostituire le attese fisse o le scadenze rigide con un polling fino a un timeout ampio, oppure rendere deterministico il codice sottoposto a test.

## Verification

Cinquanta esecuzioni consecutive sotto carico risultano verdi.
