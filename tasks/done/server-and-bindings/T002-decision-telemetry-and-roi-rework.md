# T002 Telemetria delle decisioni (`kilo_log_decision`) e rielaborazione dell'analisi ROI

- id: T002
- title: Telemetria delle decisioni (kilo_log_decision) e rielaborazione dell'analisi ROI
- category: server-and-bindings
- priority: P1
- priority-reason: Necessario per calibrare la policy di delega su dati osservabili reali anziché su stime inline non calibrate
- next-up: no
- state: done
- executor: self
- depends-on: -
- decider: -
- sources: ../architect-executor-consolidated-review.md (§1.5, §2.4, §3.1, §3.4), docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../kilo-mcp/server.py, ../kilo-mcp/test_server.py, ../kilo-mcp/kilo-mcp.example.toml, ../ai-architect-executor/plugins/architect-side/skills/delegation-roi-analysis/SKILL.template.md, ../kilo-mcp/bindings/delegation-roi-analysis.json
- handoff: Leggere tasks/server-and-bindings/T002-decision-telemetry-and-roi-rework.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: orchestrator:deep-reasoning
- short: Rielaborazione telemetria decisioni

## Goal

Registrare il ramo decisionale di orchestrazione effettivamente intrapreso (`delegate` | `inline` | `escalate` | `discarded`), esporre metriche osservabili di qualità e costo in `kilo_metrics`, affinare la `delegation_policy` di default e aggiornare `delegation-roi-analysis` / `mcp-metrics-analyst`.

## Steps

1. Aggiungere `kilo_log_decision(branch, reason, task_ref="", followup_needed=False, run_id="")` a `../kilo-mcp/server.py` con persistenza su `decisions.jsonl` sotto `DATA_DIR`.
2. Estendere `kilo_metrics` in `../kilo-mcp/server.py` per riportare i conteggi delle decisioni per ramo, il tasso di follow-up inline, il tasso di annullamento e il tasso di run completate ma scartate insieme al costo per task completato.
3. Aggiornare il default di `delegation_policy` in `../kilo-mcp/kilo-mcp.example.toml` (criteri inline espliciti: file singolo, <10 righe, nessuna modifica di logica/firma, già nel contesto; più clausola di escalation dopo 2 fallimenti).
4. Aggiornare `../ai-architect-executor/plugins/architect-side/skills/delegation-roi-analysis/SKILL.template.md` e `../kilo-mcp/bindings/delegation-roi-analysis.json` per includere le run scartate, l'inquadramento contesto/quota per configurazioni a costo marginale zero e le metriche osservabili. Rigenerare le skill e gli indici.

## Verification

- `../kilo-mcp/.venv/bin/pytest ../kilo-mcp/test_server.py` passa con i test per `kilo_log_decision` e `kilo_metrics`.
- `python3 ../kilo-mcp/scripts/regenerate_bound_skills.py --check` termina con codice 0.
